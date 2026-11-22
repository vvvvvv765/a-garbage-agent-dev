"""
大模型输出子体系（内存体系的子体系）：消费流，把模型吐出来的东西写进数据表。

为什么归内存：模型输出是本机的主要数据来源，它经数据表（内存）进入这台计算机，
是数据表在模型侧的入口。

写入：
  - 正文流式片段 → 瞬态地址 stream（给显示看，不落盘）
  - 正文整段 / 思考 / 工具调用 → 持久地址
provider 相关的事件词汇在 Provider/Adapter（共用方言）。
"""
import threading
import time

from Bus import NT, keys
from Config import Providers
from Config import config
from Contract import Contract
from Log import log
from Provider import adapter
from Turn import turn
from Usage import record as usage_record

from . import mem, STREAM, ASSISTANT, TOOL_CALL, REASONING, USAGE, EXCEPTION


def _close_stream(stream):
    for target in (stream, getattr(stream, "response", None),
                   getattr(stream, "_response", None)):
        close = getattr(target, "close", None)
        if callable(close):
            try:
                close()
                return
            except Exception:
                pass


def _watch_cancel(stream, should_stop, done):
    """等取消；用户点停止时关流，让阻塞的 read 立刻返回。"""
    while not done.wait(0.2):
        try:
            if should_stop is not None and should_stop():
                _close_stream(stream)
                return
        except Exception:
            return


class ModOutput:
    def consume(self, stream, should_stop=None, epoch=0):
        """消费一整条流；返回本轮的工具调用列表。

        should_stop：CPU 传进来的中断判定（用户点了停止）。
        epoch：CPU 的轮次序号，流片段带这个标记，渲染只消费本轮。
        中途停：已收到的正文按“部分回复”写进表，流关掉。
        """
        try:
            calls = self.__consume(stream, should_stop, epoch)
        except Exception:
            NT.register(keys.MEMORY_SIGNAL, Contract(SI=False))
            raise                      # 让重连子体系（CPU）照常重试
        NT.register(keys.MEMORY_SIGNAL, Contract(SI=True))
        return calls

    def __consume(self, stream, should_stop=None, epoch=0):
        """读流；取消时从旁路线程关掉流，别让主线程卡在 read 上等超时。"""
        if stream is None and should_stop is None:
            return self.__consume_inner(stream, should_stop, epoch)
        done = threading.Event()
        watcher = threading.Thread(
            target=_watch_cancel, args=(stream, should_stop, done), daemon=True
        )
        watcher.start()
        try:
            return self.__consume_inner(stream, should_stop, epoch)
        finally:
            done.set()

    def __consume_inner(self, stream, should_stop=None, epoch=0):
        text_parts = []
        thinking_parts = []
        calls = []
        thinking_closed = False
        started = time.perf_counter()
        first_thinking = None
        last_thinking = None
        first_text = None
        last_text = None
        thinking_deltas = 0
        text_deltas = 0
        # 整条流用同一份方言；中途切 provider 只影响下一次请求
        ad = adapter.current()

        if stream is None:
            return calls

        stopped = False
        for event in stream:
            if should_stop is not None and should_stop():
                stopped = True
                break
            if ad.is_thinking_delta(event):
                piece = str(ad.thinking_delta(event))
                thinking_parts.append(piece)
                thinking_deltas += 1
                last_thinking = (time.perf_counter() - started) * 1000
                if first_thinking is None:
                    first_thinking = last_thinking
                mem.push_transient(               # 思考片段：瞬态，只给显示看，不落盘
                    STREAM, {"delta": piece, "epoch": epoch, "thinking": True}
                )
            elif ad.is_text_delta(event):
                if thinking_parts and not thinking_closed:
                    # 思考 → 正文的边界：先让显示把思考块收尾
                    mem.push_transient(
                        STREAM, {"end": True, "epoch": epoch, "thinking": True}
                    )
                    thinking_closed = True
                delta = ad.text_delta(event)
                text_parts.append(delta)
                text_deltas += 1
                last_text = (time.perf_counter() - started) * 1000
                if first_text is None:
                    first_text = last_text
                mem.push_transient(               # 流式片段：瞬态，带轮次 epoch
                    STREAM, {"delta": delta, "epoch": epoch}
                )
            elif ad.is_completed(event):
                if thinking_parts and not thinking_closed:
                    mem.push_transient(
                        STREAM, {"end": True, "epoch": epoch, "thinking": True}
                    )
                    thinking_closed = True
                text = "".join(text_parts)
                reasoning_items = []

                for item in ad.completed_output(event):
                    kind = ad.item_type(item)
                    if kind == "reasoning":
                        block = ad.dump_reasoning(item)
                        if isinstance(block, dict):
                            block = dict(block)
                            # 记下这是哪家方言产出的：跨方言回灌会 400，GPU 组装时据此过滤
                            block["_dialect"] = Providers.current_kind(config)
                        reasoning_items.append(block)
                    elif kind == "function_call":
                        calls.append(ad.tool_call(item))

                # 顺序：思考块 -> 正文 -> 工具调用（与模型输出一致）
                if text_parts:
                    mem.push_transient(
                        STREAM, {"end": True, "epoch": epoch}
                    )  # 告诉显示：这段画完了
                for item in reasoning_items:
                    mem.submit(REASONING, item)
                if text:
                    mem.submit(ASSISTANT, text)
                for call in calls:
                    mem.submit(TOOL_CALL, call)
                if getattr(event, "truncated", False):
                    mem.submit(EXCEPTION, {
                        "system": "Adapter",
                        "where": "chat",
                        "kind": "Warning",
                        "message": "模型输出命中 token 上限，工具参数可能被截断",
                    })

                usage = ad.usage(event)
                if usage:
                    item = usage_record(
                        usage,
                        "chat",
                        model=str(config.get("llm.model", "")),
                        provider=str(config.get("llm.provider_id", "")),
                        pricing=config.get("llm.pricing", {}) or {},
                    )
                    item["turn"] = turn.current()
                    mem.submit(USAGE, item)

        if stopped:
            text = "".join(text_parts)
            if thinking_parts and not thinking_closed:
                mem.push_transient(
                    STREAM, {"end": True, "epoch": epoch, "thinking": True}
                )
            if text_parts:
                mem.push_transient(
                    STREAM, {"end": True, "epoch": epoch}
                )
            if text:
                mem.submit(ASSISTANT, text)   # 半截回复也留痕
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        self.__log_timing(
            (first_thinking, last_thinking, thinking_deltas, len("".join(thinking_parts))),
            (first_text, last_text, text_deltas, len("".join(text_parts))),
        )
        return calls

    @staticmethod
    def __log_timing(thinking, text):
        """流的水温：首段 / 末段到达时间 + 分段数。

        网关到底是逐字下发、均匀吐字，还是整块攒完再吐，看这行就够。
        """
        def part(name, first, last, count, chars):
            def mark(value):
                return "—" if value is None else f"+{value:.0f}ms"
            span = "" if (first is None or last is None) else f" span={last - first:.0f}ms"
            return (
                f"{name} first={mark(first)} last={mark(last)}{span} "
                f"{count} deltas/{chars} chars"
            )

        log.info(
            "Memory",
            "stream: "
            + part("thinking", *thinking)
            + "; "
            + part("text", *text),
        )


modo = ModOutput()
