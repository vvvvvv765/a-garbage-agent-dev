"""
渲染体系：给人看的输出（Agent 计算机的第二个 GPU）

它不是被调用的函数，而是一条**常驻执行流**：
  - CPU 在信息表下「开始 / 停止」指令（keys.CPU_RENDER）
  - 启用期间自己按序消费数据表：
        正文流式片段  → 瞬态地址 stream
        工具调用 / 结果 / 异常 → 持久记录
  - 页面刷新用 history() 从持久记录回放（不依赖线程）

读表不是体系间交流——数据表谁都能读，所以不需要谁来"叫"它。
"""
import json
import os
import sys
import threading
import time

from Bus import NT, keys
from Contract import InstructionQueue
from Faults import faults
from Memory import mem
from Memory.Addresses import (
    USER, STREAM, ASSISTANT, REASONING, TOOL_CALL, TOOL_OUTPUT, EXCEPTION, USAGE,
)
from Turn import turn


def reasoning_text(payload):
    """从 reasoning 记录里抽显示文本（summary / content 里的 text）。"""
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    parts = []
    for key in ("summary", "content"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif isinstance(item, str):
                parts.append(item)
    if payload.get("thinking"):
        parts.append(str(payload["thinking"]))
    return "\n\n".join(parts).strip()


def _console_style(text, code):
    """只在支持 ANSI 的交互终端着色；重定向输出与 NO_COLOR 保持纯文本。"""
    try:
        enabled = bool(sys.stdout.isatty()) and "NO_COLOR" not in os.environ
    except Exception:
        enabled = False
    if os.name == "nt" and not any((
        os.environ.get("WT_SESSION"), os.environ.get("ANSICON"),
        os.environ.get("ConEmuANSI", "").upper() == "ON",
    )):
        enabled = False
    return f"\033[{code}m{text}\033[0m" if enabled else str(text)


def _console_tool_summary(name, arguments):
    """工具头只显示最有用的一项；完整参数仍可在 Web 工具卡片查看。"""
    try:
        value = json.loads(arguments) if isinstance(arguments, str) else arguments
    except (TypeError, ValueError):
        value = arguments
    if isinstance(value, dict):
        keys = ("bashinput", "command", "path", "query", "url", "text")
        summary = next((value[key] for key in keys if isinstance(value.get(key), str) and value[key].strip()), "")
        if not summary:
            summary = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    else:
        summary = str(value or "")
    summary = " ".join(str(summary).split())
    return summary if len(summary) <= 180 else summary[:177] + "…"


class Renderer:
    def __init__(self, memory=None, bus=None, session_id=""):
        self.__mem = memory if memory is not None else mem
        self.__nt = bus if bus is not None else NT
        self.session_id = str(session_id or "")
        self.__line_open = False
        self.__assistant_open = False
        self.__reasoning_open = False  # 正在流式画思考块
        self.__sinks = []
        self.__console = True

        # 常驻执行流
        self.__thread = None
        self.__halt = threading.Event()
        self.__last_seq = 0
        self.__stream_seen = 0     # 已消费的瞬态片段数
        self.__stream_ends = 0     # 已消费的"流式结束"标记数（对应后面的正文整段记录）
        self.__reasoning_ends = 0  # 同上，思考块
        self.__enabled = True      # 电平：是否在消费（start / stop 是边沿事件）
        self.__epoch = 0           # CPU 的轮次序号：只消费本轮的 stream
        self.__sync_lock = threading.Lock()
        self.__call_names = {}     # call_id -> 工具名（结果行要显示名字）

        # 运行期健康（SI 是启动自检，这里管“显示线程还活着吗”）
        self.__faults = faults.for_system("Render")
        self.__healthy = True
        self.__error = ""
        self.__failures = 0
        self.__last_error = ""

    # ---------- 出口 ----------
    def add_sink(self, sink):
        """注册一个事件接收函数（事件是 dict，可直接 JSON 化）。"""
        self.__sinks.append(sink)

    @property
    def alive(self):
        thread = self.__thread
        return bool(thread is not None and thread.is_alive())

    def status(self):
        """显示线程的运行期健康：Web / 诊断用（SI 只管启动，这里管存活）。"""
        return {
            "alive": self.alive,
            "healthy": bool(self.__healthy),
            "error": self.__error,
        }

    def set_console(self, enabled):
        self.__console = bool(enabled)

    def __emit(self, event):
        # 实时事件带上轮次号（回放的事件来自落盘记录，没有轮次号）
        event.setdefault("turn", turn.current())
        for sink in list(self.__sinks):
            try:
                sink(event)
            except Exception:
                pass

    # ---------- 生命周期（由主板开 / 由 CPU 关机时收） ----------
    def start(self):
        """起常驻显示线程：从数据表当前末尾开始看（历史由 /api/history 回放）。"""
        if self.__thread is not None and self.__thread.is_alive():
            return
        # 位置用绝对水位：退役后主表不再从 seq 1 开始
        self.__last_seq = self.__mem.last_seq()
        self.__stream_seen = self.__mem.transient_total(STREAM)   # 绝对计数游标
        self.__stream_ends = 0
        self.__reasoning_ends = 0
        self.__reasoning_open = False
        self.__epoch = 0
        self.__enabled = True
        self.__halt.clear()
        self.__healthy = True
        self.__error = ""
        self.__failures = 0
        self.__last_error = ""
        self.__thread = threading.Thread(target=self.__loop, name="Render", daemon=True)
        self.__thread.start()

    def shutdown(self):
        self.__halt.set()
        thread = self.__thread
        self.__thread = None
        if thread is not None:
            thread.join(timeout=2)
        with self.__sync_lock:
            self.__apply_events()
            self.__drain()
        self.__finish_line()

    def reset_position(self):
        """切换会话后：从数据表当前末尾开始看，不重画已载入的历史。"""
        with self.__sync_lock:
            self.__last_seq = self.__mem.last_seq()
            self.__stream_seen = self.__mem.transient_total(STREAM)
            self.__stream_ends = 0
            self.__reasoning_ends = 0
            self.__reasoning_open = False
            self.__epoch = 0

    def sync(self, timeout=1.0):
        """真正的同步点（关机 / 切会话）：有界地把当前显示数据消费完。"""
        thread = self.__thread
        if thread is None or not thread.is_alive():
            with self.__sync_lock:
                self.__apply_events()
                self.__drain()
            return True
        acquired = self.__sync_lock.acquire(timeout=max(0.0, timeout))
        if not acquired:
            return False
        try:
            self.__apply_events()
            self.__drain()
            return True
        finally:
            self.__sync_lock.release()

    # ---------- 主循环 ----------
    def __loop(self):
        while not self.__halt.is_set():
            try:
                revision = self.__mem.revision()
                with self.__sync_lock:
                    self.__apply_events()
                    if self.__enabled:
                        self.__drain()
                if self.__mem.revision() == revision:
                    self.__mem.wait_revision(revision, timeout=0.2)
            except Exception as error:
                # 显示线程不能静默死掉：写异常表 + 日志，退避后继续（坏记录会被跳过）
                self.__healthy = False
                self.__error = f"{type(error).__name__}: {error}"
                self.__failures += 1
                fingerprint = self.__error
                if fingerprint != self.__last_error:
                    self.__last_error = fingerprint
                    self.__faults.report(error, "render_loop")
                time.sleep(min(2.0, 0.2 * self.__failures))
            else:
                self.__failures = 0
                if not self.__healthy:
                    self.__healthy = True
                    self.__error = ""
                    self.__last_error = ""

    def __apply_events(self):
        """边沿信号按序消费：stop 先 drain 再关，start 再开；seq 只增。"""
        control = self.__nt.get(keys.CPU_RENDER)
        if not isinstance(control, InstructionQueue):
            return
        for event in control.take():
            if event.action == "start":
                self.__enabled = True
                # 轮次边界清零：配对计数绝不能跨轮残留，否则后面某一轮的整段回复会被吞
                self.__stream_ends = 0
                self.__reasoning_ends = 0
                if event.seq:
                    self.__epoch = event.seq   # 旧 epoch 的 stream 片段跳过
            elif event.action == "stop":
                self.__drain()                 # 停之前把已有的画完
                self.__finish_reasoning()
                self.__finish_line()
                self.__mem.clear_transient(STREAM)    # 轮末清空瞬态
                self.__stream_seen = 0
                self.__stream_ends = 0
                self.__reasoning_ends = 0
                self.__enabled = False

    def __drain(self):
        self.__drain_stream()
        self.__drain_records()

    def __drain_stream(self):
        items, total = self.__mem.transient_window(STREAM)  # 同一把锁：内容和绝对计数对齐
        window_start = max(0, total - len(items))     # 当前窗口第一条的绝对序号
        if self.__stream_seen < window_start:
            # 中间片段被容量挤掉了：从当前窗口开头接着画，尾段照常处理
            self.__stream_seen = window_start
        offset = max(0, self.__stream_seen - window_start)
        for item in items[offset:]:
            if isinstance(item, dict):
                item_epoch = int(item.get("epoch", self.__epoch) or 0)
                if item_epoch and item_epoch != self.__epoch:
                    continue          # 上一轮残留的片段：不画
                if item.get("thinking"):
                    if item.get("end"):
                        if self.__reasoning_open:
                            self.__reasoning_ends += 1
                        self.__finish_reasoning()
                    elif "delta" in item:
                        self.reasoning_delta(str(item["delta"]))
                    continue
                if item.get("tool"):
                    call_id = str(item.get("call_id") or "")
                    if call_id and "delta" in item:
                        self.__emit({
                            "type": "tool_delta",
                            "call_id": call_id,
                            "text": str(item["delta"]),
                        })
                    continue
                if item.get("end"):
                    # 只记“这一段流画完了”，真正的 assistant_end 等整段记录到了再发，
                    # 这样前端可以先拿到全文校正（丢片段也能补回来）。
                    self.__stream_ends += 1
                    self.__close_line()
                elif "delta" in item:
                    self.assistant_delta(str(item["delta"]))
                else:
                    self.assistant_delta(str(item))
            else:
                self.assistant_delta(str(item))
        self.__stream_seen = total

    def __drain_records(self):
        records = self.__mem.records_after(self.__last_seq)
        if not records:
            if self.__last_seq > self.__mem.last_seq():
                self.__last_seq = 0       # 内存被清空（新会话）后重来
            return
        for record in records:
            self.__last_seq = record.seq
            self.__draw(record)

    def __draw(self, record):
        address = record.address
        payload = record.payload

        if address == ASSISTANT:
            text = str(payload or "")
            if self.__stream_ends > 0:
                # 这段正文流式画过：把**整段原文**给前端校正（SSE 丢字也能补回来），
                # 再收尾。流式中间不发 assistant_end，避免前端提前定稿。
                self.__stream_ends -= 1
                self.__emit({"type": "assistant_final", "text": text})
                self.__finish_line()
            elif text:
                self.__finish_line()
                self.assistant_message(text)
                self.__emit({"type": "assistant_end"})

        elif address == TOOL_CALL:
            item = payload if isinstance(payload, dict) else {}
            call_id = item.get("call_id")
            if call_id:
                self.__call_names[call_id] = item.get("name", "")
            self.tool_call(
                item.get("name", ""), item.get("arguments", ""), call_id or ""
            )

        elif address == TOOL_OUTPUT:
            item = payload if isinstance(payload, dict) else {}
            call_id = str(item.get("call_id") or "")
            self.tool_result(
                self.__call_names.get(call_id, ""),
                str(item.get("output") or ""),
                call_id,
            )

        elif address == EXCEPTION:
            item = payload if isinstance(payload, dict) else {}
            self.exception(item)

        elif address == REASONING:
            if self.__reasoning_ends > 0:
                # 这段思考已经流式画过，整段记录只用于落盘 / 回灌
                self.__reasoning_ends -= 1
                return
            text = reasoning_text(payload)
            if text:
                self.reasoning(text)

        elif address == USAGE:
            # 账本进了数据表：通知前端刷新统计（不要画成对话内容）
            self.__emit({"type": "usage"})

        # USER / REASONING / SUMMARY：不画
        # （用户输入由控制台自己敲 / 网页自己加；思考和摘要属于内部数据）

    # ---------- 回放 ----------
    def history(self, records):
        """把内存记录翻译成显示事件（页面刷新 / 重连时用）。

        只还原给人看的部分：用户、正文、工具、异常。
        思考、摘要属于内部数据，不显示。
        """
        events = []
        call_names = {}

        for record in records:
            address = record.address
            payload = record.payload

            if address == USER:
                if isinstance(payload, dict):
                    images = [
                        {"url": f"/api/upload/{item.get('id')}"}
                        for item in (payload.get("images") or [])
                        if isinstance(item, dict) and item.get("id")
                    ]
                    events.append({
                        "type": "user_message",
                        "text": str(payload.get("text") or ""),
                        "images": images,
                    })
                else:
                    events.append({"type": "user_message", "text": str(payload or "")})

            elif address == ASSISTANT:
                text = str(payload or "")
                if text:
                    events.append({"type": "assistant_message", "text": text})

            elif address == TOOL_CALL:
                item = payload if isinstance(payload, dict) else {}
                call_id = item.get("call_id")
                name = item.get("name", "")
                if call_id:
                    call_names[call_id] = name
                events.append({
                    "type": "tool_call",
                    "name": name,
                    "arguments": item.get("arguments", ""),
                })

            elif address == TOOL_OUTPUT:
                item = payload if isinstance(payload, dict) else {}
                call_id = item.get("call_id")
                content = str(item.get("output") or "")
                if len(content) > 4000:
                    content = content[:4000] + "\n…（回放已截断，完整内容见落盘路径）"
                events.append({
                    "type": "tool_result",
                    "name": call_names.get(call_id, ""),
                    "content": content,
                })

            elif address == REASONING:
                text = reasoning_text(payload)
                if text:
                    if len(text) > 4000:
                        text = text[:4000] + "\n…（思考较长，回放已截断）"
                    events.append({"type": "reasoning", "text": text})

            elif address == EXCEPTION:
                item = payload if isinstance(payload, dict) else {}
                events.append({
                    "type": "error",
                    "message": (
                        f"[{item.get('system', '')}] {item.get('where', '')}: "
                        f"{item.get('kind', '')}: {item.get('message', '')}"
                    ),
                })

        return events

    # ---------- 事件 ----------
    def assistant_delta(self, delta):
        self.__finish_reasoning()   # 正文开头时思考必然已经结束（兜底）
        self.__assistant_open = True
        self.__emit({"type": "assistant_delta", "text": delta})
        if not self.__console:
            return
        if not self.__line_open:
            print(_console_style("✦ Spirit", "1;38;5;173"), flush=True)
            self.__line_open = True
        print(delta, flush=True, end="")

    def assistant_message(self, text):
        """整段正文（没有流式片段时的兜底显示）。"""
        self.__finish_line()
        self.__emit({"type": "assistant_message", "text": text})
        if not self.__console:
            return
        print(f"{_console_style('✦ Spirit', '1;38;5;173')}\n{text}", flush=True)

    def __close_line(self):
        """只关控制台那一行，不发 assistant_end（等整段记录到了再收尾）。"""
        if self.__console and self.__line_open:
            print(flush=True)
            self.__line_open = False

    def __finish_line(self):
        if self.__assistant_open:
            self.__emit({"type": "assistant_end"})
            self.__assistant_open = False
        if not self.__console:
            return
        if self.__line_open:
            print(flush=True)
            self.__line_open = False

    def reasoning_delta(self, delta):
        """思考片段：和正文一样逐段上屏，但走 reasoning_delta 事件。"""
        self.__finish_line()
        if not self.__reasoning_open:
            self.__reasoning_open = True
            if self.__console:
                print(_console_style("◇ 深度思考", "2"), flush=True)
        self.__emit({"type": "reasoning_delta", "text": delta})
        if self.__console:
            print(_console_style(delta, "2"), flush=True, end="")

    def __finish_reasoning(self):
        if self.__reasoning_open:
            self.__emit({"type": "reasoning_end"})
            self.__reasoning_open = False
            if self.__console:
                print(flush=True)

    def reasoning(self, text):
        """整段思考（没有流式片段时的兜底显示）。"""
        self.__finish_reasoning()
        self.__finish_line()
        self.__emit({"type": "reasoning", "text": text})
        if not self.__console:
            return
        print(f"{_console_style('◇ 深度思考', '2')}\n{text}", flush=True)

    def tool_call(self, name, arguments, call_id=""):
        self.__finish_line()
        self.__emit({
            "type": "tool_call", "name": name,
            "arguments": arguments, "call_id": call_id,
        })
        if not self.__console:
            return
        print(_console_style(f"⏺ {name}", "1"), flush=True)
        summary = _console_tool_summary(name, arguments)
        if summary:
            print(f"  {summary}", flush=True)

    def tool_result(self, name, output, call_id="", limit=300):
        text = output or ""
        self.__emit({
            "type": "tool_result", "name": name,
            "content": text[:8000], "call_id": call_id,
        })
        if not self.__console:
            return
        shown = text if len(text) <= limit else text[:limit] + "…（已截断）"
        label = name or "结果"
        print(_console_style(f"  ⎿ {label}", "2"), flush=True)
        for line in shown.splitlines() or ["（无输出）"]:
            print(f"    {line}", flush=True)

    def error(self, msg):
        self.__finish_line()
        self.__emit({"type": "error", "message": msg})
        if not self.__console:
            return
        print(f"{_console_style('⨯', '31;1')} {msg}", flush=True)

    def exception(self, item):
        self.__finish_line()
        self.__emit({
            "type": "exception",
            "system": item.get("system", ""),
            "where": item.get("where", ""),
            "kind": item.get("kind", ""),
            "message": item.get("message", ""),
        })
        if not self.__console:
            return
        print(
            f"{_console_style('⨯', '31;1')} "
            f"{item.get('system', '')} · {item.get('where', '')}: "
            f"{item.get('kind', '')}: {item.get('message', '')}",
            flush=True,
        )


render = Renderer()
