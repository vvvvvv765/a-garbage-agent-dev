"""
该模块属于 Agent 计算机思想中的 CPU 体系

CPU 只负责调度：
  启动阶段 -> 注册控制信号（不读别人的报告）
  循环阶段 -> 调用户输入 -> 调大模型 -> 调度能力体系 -> 写内存
能力的执行与结果加工，都由能力体系自己完成。
"""
import json
import time

from Bus import NT, keys
from Cancel import CancelToken, token as cancel_token
from Capabilities import CapabilityInput
from Config import config
from Contract import Contract, ThinkingControl, Instruction, InstructionQueue
from Faults import faults
from Log import log
from Memory.Addresses import TOOL_CALL   # 地址词表 = 数据表协议的一部分（常量，不是体系行为）
from Turn import turn

from .Failover import failover
from .Guard import guard
from .Reconnect import reconnect
from .Security import security


def _max_steps():
    """每轮工具回环上限；<=0 表示不限（Claude 式：靠停止 / 重复拦截 / 预算兜底）。"""
    try:
        value = int(config.get("engine.max_steps", 0))
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


class CPU:
    def __init__(
        self, memory=None, bus=None, security_=None, cancel=None,
        session_id="", owns_capabilities=True,
    ):
        self.__mem = memory
        self.__nt = bus if bus is not None else NT
        self.__security = security_ if security_ is not None else security
        self.session_id = str(session_id or "primary")
        # 能力体系是整机共享的：只有主会话的 CPU 负责在关机时收掉它
        self.owns_capabilities = bool(owns_capabilities)
        self.start = True
        self.skip = False
        self.thinking = bool(config.get("engine.thinking", False))
        self.effort = self.__check_effort(config.get("llm.reasoning", "high"))
        self.max_steps = _max_steps()
        self.__faults = faults.for_system("CPU")
        self.__interrupt = cancel if cancel is not None else cancel_token
        self.__render_seq = 0                  # 渲染指令序号（每轮 +1）
        self.__turn_id = 0                     # 当前轮次号（日志 / 审计 / 用量 / 渲染共用）
        self.turn_active = False               # 正在处理一轮（不含等用户输入）
        self.state = "idle"                   # idle / waiting_model / running_tools

        # 装配句柄：主板开机前注入（CPU 不 import 主体系的单例）
        self.__gpu = None
        self.__memory = None
        self.__input = None
        self.__switch_provider = None   # 故障转移：激活另一家提供商并重建客户端

    def attach(self, gpu=None, memory=None, input_source=None, switch_provider=None):
        """装配：主体系把句柄交给 CPU（同步口）。

        判据 4 的同步形态：主体系之间不 import，由主板把句柄注入 CPU；
        不阻塞的边沿（如渲染启停）仍走信息表的指令队列。
        """
        if gpu is not None:
            self.__gpu = gpu
        if memory is not None:
            self.__memory = memory
        if input_source is not None:
            self.__input = input_source
        if switch_provider is not None:
            self.__switch_provider = switch_provider

    def attached(self):
        """装配状态（诊断用）。"""
        return {
            "gpu": self.__gpu is not None,
            "memory": self.__memory is not None,
            "input": self.__input is not None,
            "failover": self.__switch_provider is not None,
        }

    def boot(self):
        """启动阶段：只注册控制信号 + 检查 BIOS 报告。"""
        # 允许同一个进程里重新启动引擎（上次 run 结束时 start 已被置 False）
        self.start = True
        self.skip = False
        self.__nt.register(keys.CPU_USER, Contract(should_process=True))
        self.__nt.register(keys.CPU_MOD, Contract(should_process=True))
        self.__nt.register(keys.CPU_THINKING, ThinkingControl(
            should_process=self.thinking,
            effort=self.effort,
        ))

        # 显示体系：开机即进入"处理显示数据"状态（开机阶段的异常也要能看见）
        # 同一个进程里重新开机时复用原队列（句柄不重复登记）
        queue = self.__nt.get(keys.CPU_RENDER)
        if not isinstance(queue, InstructionQueue):
            queue = InstructionQueue()
            self.__nt.register(keys.CPU_RENDER, queue)

        missing = [
            name for name, handle in (
                ("GPU", self.__gpu),
                ("内存", self.__memory),
                ("用户输入", self.__input),
            ) if handle is None
        ]
        bios = self.__nt.get(keys.AGENT_START)
        if missing:
            self.__faults.report_message(f"CPU 未装配：{'、'.join(missing)}", "boot")
            log.error("CPU", f"boot failed: missing {missing}")
            self.start = False
        elif bios is None or not bios.SI:
            self.__faults.report_message("BIOS 启动失败，Agent 无法开机", "boot")
            log.error("CPU", "boot failed: BIOS")
            self.start = False
        else:
            log.info("CPU", "boot ok")

    def run(self):
        if not self.start:
            return
        try:
            while self.start:
                try:
                    self.__turn()
                except Exception as error:
                    self.__faults.report(error, "turn")
        finally:
            capability_system = self.__nt.get(keys.CAPABILITIES)
            if capability_system is not None and self.owns_capabilities:
                capability_system.shutdown()
            if self.__memory is not None:
                self.__memory.save()
            log.info("CPU", "shutdown")
            if self.__memory is not None:
                self.__memory.stop()

    def __turn(self):
        """一轮：用户输入 -> 请求 / 流 -> 工具循环 -> 落盘。"""
        self.__turn_id = turn.begin()
        log.info("CPU", f"turn start (turn={self.__turn_id})")
        self.__set_render("start")      # 指令：显示体系开始处理显示数据
        try:
            self.__turn_body()
        finally:
            # 会话锁由输入体系在“真正拿到消息”后接管，CPU 在轮末释放；
            # 等输入的空闲期不占锁，否则新建 / 切会话永远被 409 挡住。
            release = getattr(self.__input, "release_session_lock", None)
            if callable(release):
                release()
            self.__set_render("stop")   # 指令：停止

    def __turn_body(self):
        self.__interrupt.clear()
        guard.reset()
        # 思考开关在轮次边界应用（工具循环内保持不变）
        ctrl = self.__nt.get(keys.CPU_THINKING)
        if ctrl is not None:
            ctrl.should_process = self.thinking
            ctrl.effort = self.effort
        self.__input.uim()
        self.__read_user_report()
        if not self.start:
            log.info("CPU", "turn: shutdown requested")
            return
        if self.skip:
            log.info("CPU", "turn: skipped")
            self.skip = False
            return

        self.__security.clear_untrusted()   # 新的一轮从用户指令开始算干净
        self.turn_active = True   # 从这一刻起不允许切场景
        try:
            stop = guard.budget_stop()
            if stop:
                self.__faults.report_message(f"{stop}，本轮不再请求模型", "budget")
                log.warning("CPU", stop)
                self.__memory.save()
                return

            self.state = "waiting_model"
            calls = self.__ask_model()
            self.__checkpoint("model")   # 模型回复 / 工具调用先落盘，工具再久也不怕中途退出
            steps = 0
            while calls and (self.max_steps <= 0 or steps < self.max_steps):
                self.state = "running_tools"
                outputs = self.__run_tools(calls)
                self.__checkpoint("tools")
                for output in outputs:
                    if (getattr(output, "meta", {}) or {}).get("trust") == "untrusted":
                        self.__security.note_untrusted(
                            (output.meta or {}).get("source") or "工具结果"
                        )
                log.info("CPU", f"tools done: {len(outputs)}")
                if self.__interrupt.is_set():
                    # 用户点了停止：工具已经收掉，不再让模型接着做
                    log.info("CPU", "turn interrupted during tools")
                    break
                stop = guard.budget_stop()
                if stop:
                    self.__faults.report_message(f"{stop}，本轮不再请求模型", "budget")
                    log.warning("CPU", stop)
                    break
                self.state = "waiting_model"
                calls = self.__ask_model()
                self.__checkpoint("model")
                steps += 1

            log.info(
                "CPU",
                f"turn end (turn={self.__turn_id}): "
                f"steps={steps} pending_calls={len(calls)}",
            )
            if calls and self.max_steps > 0 and steps >= self.max_steps:
                self.__faults.report_message(
                    f"工具跟进超过 {self.max_steps} 步，停止本轮", "max_steps"
                )
                log.warning("CPU", f"tool loop hit MAX_STEPS={self.max_steps}")
        finally:
            self.turn_active = False
            self.state = "idle"
            self.__checkpoint("turn-end")   # 异常 / 中断路径也要落盘

    def __checkpoint(self, reason=""):
        """轮内检查点：把新记录追加落盘（保存本身只写增量，代价很小）。

        不落盘的窗口从“一整轮”缩到“一次模型调用 / 一批工具”。
        """
        if self.__memory is None:
            return
        try:
            self.__memory.save()
        except Exception as error:
            self.__faults.report(error, f"checkpoint:{reason or '-'}")

    def __set_render(self, action):
        """信息表里的指令：让显示体系开始 / 停止处理显示数据（带轮次序号）。"""
        if action == "start":
            self.__render_seq += 1
        queue = self.__nt.get(keys.CPU_RENDER)
        if not isinstance(queue, InstructionQueue):
            queue = InstructionQueue()
            self.__nt.register(keys.CPU_RENDER, queue)
        queue.push(Instruction(
            target="render", action=action, seq=self.__render_seq
        ))

    def interrupt(self):
        """中断当前轮：模型流 + 工具 + 挂起审批 + 摘要，一次全取消。"""
        self.__interrupt.set()
        self.__security.cancel_pending()
        capability_system = self.__nt.get(keys.CAPABILITIES)
        count = 0
        if capability_system is not None:
            cancel = getattr(capability_system, "cancel_all", None)
            if callable(cancel):
                count = cancel("用户停止", session_id=self.session_id)
        log.info("CPU", f"interrupt requested (tools cancelled: {count})")

    def refresh_config(self):
        """从当前配置重读启动参数（Engine 构造时调；轮次内不调）。"""
        self.max_steps = _max_steps()
        self.thinking = bool(config.get("engine.thinking", False))
        self.effort = self.__check_effort(config.get("llm.reasoning", "high"))

    def set_thinking(self, on, effort=None):
        """思考开关 / 强度：只改 CPU 状态；**下一轮开始**才应用到总线。

        按 API 规则，思考开关只能在轮次之间切换，工具循环内不切。
        """
        self.thinking = bool(on)
        if effort is not None:
            self.effort = self.__check_effort(effort)
        log.info(
            "CPU",
            f"thinking pending {'on' if self.thinking else 'off'} "
            f"effort={self.effort} (next turn)",
        )

    @staticmethod
    def __check_effort(value):
        value = str(value or "").lower()
        value = {"minimal": "low", "medium": "high", "xhigh": "high",
                 "ultra": "max"}.get(value, value)
        return value if value in {"low", "high", "max"} else "high"

    def __read_user_report(self):
        """读用户输入体系的报告（上行）。"""
        report = self.__nt.get(keys.USER_INPUT)
        if report is None:
            return
        self.start = bool(report.start)
        self.skip = bool(report.skip)

    def __ask_model_once(self):
        """一次「请求 + 消费」（内含 Reconnect 的退避重试）。"""
        return reconnect.chat(
            self.__gpu.request,
            lambda stream: self.__memory.consume(
                stream, self.__interrupt.is_set, self.__render_seq
            ),
        )

    def __try_failover(self, result):
        """请求失败后，按 cc-switch 的有序队列换下一家再试。

        - 关着 / 没有注入切换口 / 队列里没有下一家 → 原样返回
        - 熔断中的提供商跳过（连续失败达阈值 → 冷却 cooldown 秒）
        - 换一家后失败，继续找下一家；全试完仍失败就交回原错误
        """
        current = failover.current()
        failover.record(current, False)
        if not failover.enabled() or self.__switch_provider is None:
            return result

        tried = set()
        try:
            budget = float(config.get("engine.failover.total_timeout", 180) or 0)
        except (TypeError, ValueError):
            budget = 180.0
        started = time.monotonic()
        while True:
            if budget > 0 and time.monotonic() - started > budget:
                log.warning("CPU", f"failover budget {budget:g}s exceeded")
                return result
            candidate = failover.next_after(current)
            if not candidate or candidate in tried:
                return result
            tried.add(candidate)
            failover.note_origin(current)
            log.warning("CPU", f"failover: {current} -> {candidate}")
            if not self.__switch_provider(candidate):
                failover.record(candidate, False)
                current = candidate
                continue
            try:
                attempt = self.__ask_model_once()
            except Exception as error:
                self.__faults.report(error, "failover")
                attempt = None
            if attempt is not None and attempt.ok:
                failover.record(candidate, True)
                log.info("CPU", f"failover ok: {candidate}")
                return attempt
            failover.record(candidate, False)
            current = candidate

    def __preempt_failover(self):
        """请求之前：当前提供商在熔断冷却期，就直接换到队列里的下一家。"""
        if not failover.enabled() or self.__switch_provider is None:
            return
        # 新的一轮：主家恢复了就先回切（一轮一次，避免来回抖）
        primary = failover.take_primary(turn.current())
        if primary and self.__switch_provider(primary):
            log.info("CPU", f"failover return primary: {primary}")
            failover.origin = ""
            return
        if not failover.should_preempt():
            return
        candidate = failover.next_after(failover.current())
        if not candidate:
            return
        failover.note_origin(failover.current())
        log.warning("CPU", f"failover preempt: {failover.current()} -> {candidate}")
        self.__switch_provider(candidate)

    def __ask_model(self):
        mark = self.__memory.last_seq()      # 数据表水位（O(1)，本轮之前）
        self.__preempt_failover()
        try:
            result = self.__ask_model_once()
            if result.ok:
                failover.record(failover.current(), True)
            else:
                result = self.__try_failover(result)
        except Exception as error:
            self.__faults.report(error, "ask_model")
            return []
        if not result.ok:
            self.__faults.report_message(result.error or "大模型请求失败", "chat")
            return []

        # 读 GPU 的报告：它这轮没有出包 → 本轮放弃
        gpu_report = self.__nt.get(keys.GPU_SIGNAL)
        if gpu_report is not None and gpu_report.SI is False:
            self.__faults.report_message("GPU 本轮没有出包，放弃本轮", "gpu")
            return []

        # CPU 不搬数据：本轮新增的 tool_call 自己从表里读（按 call_id 去重，防重试残留）
        self.__memory.flush()
        calls = {}
        for record in self.__memory.records_after(mark):
            if record.address == TOOL_CALL and isinstance(record.payload, dict):
                call_id = record.payload.get("call_id")
                if call_id:
                    calls[call_id] = record.payload
        log.info("CPU", f"model ok: calls={len(calls)}")
        return list(calls.values())

    def __run_tools(self, calls):
        """把模型调用翻译成 CapabilityInput，交给能力体系（执行/校验/写表都在它那边）。"""
        capability_system = self.__nt.get(keys.CAPABILITIES)
        if capability_system is None:
            self.__faults.report_message("能力体系未挂载", "capabilities")
            return []

        inputs = []
        for call in calls:
            raw = call["arguments"]

            if guard.repeated(call["name"], raw):
                inputs.append(CapabilityInput(
                    call_id=call["call_id"],
                    name=call["name"],
                    raw_arguments=raw,
                    arguments=None,
                    error=(
                        "重复调用已拦截：相同参数的调用已经做过多次，"
                        "结果不会变；请换方法或先检查上一次结果"
                    ),
                ))
                continue

            try:
                arguments = json.loads(raw) if raw else {}
                error = None
            except json.JSONDecodeError as exc:
                arguments = None
                error = f"参数不是合法 JSON：{exc}"

            # 沙箱硬边界：越界的调用直接拒绝，不浪费一次用户审批
            approved = False
            if error is None:
                ok, reason = capability_system.precheck(
                    call["name"], arguments or {}
                )
                if not ok:
                    info = capability_system.last_denial()
                    if info.get("kind") == "outside" and info.get("target"):
                        # 设置里开了「自动允许」，或操作模式是自动：本次运行内不再问
                        if (bool(config.get("engine.sandbox.auto_allow_outside", False))
                                or self.__security.mode == "auto"):
                            capability_system.grant_session(info["target"])
                            ok, reason = capability_system.precheck(
                                call["name"], arguments or {}
                            )
                            approved = bool(ok)
                            log.info("CPU", f"outside auto-allowed: {info['target']}")
                        # 工作区外：照 Claude 的做法先问用户"允许这次吗"
                        elif self.__security.request_access(
                            call["name"], call.get("call_id", ""), info
                        ):
                            if self.__security.access_scope == "session":
                                capability_system.grant_session(info["target"])
                            else:
                                capability_system.grant_once(info["target"])
                            ok, reason = capability_system.precheck(
                                call["name"], arguments or {}
                            )
                            approved = bool(ok)
                            log.info("CPU", f"access granted once: {info['target']}")
                    if not ok:
                        arguments = None
                        error = reason
                        log.info("CPU", f"sandbox deny {call['name']} {call.get('call_id', '')}")

            # 安全闸：参数 / 边界都没问题才问用户（访问刚授权过就不再重复问）
            if error is None:
                allowed, reason = self.__security.check(
                    call["name"], raw, call.get("call_id", ""), approved=approved
                )
                if not allowed:
                    arguments = None
                    error = reason

            inputs.append(CapabilityInput(
                call_id=call["call_id"],
                name=call["name"],
                raw_arguments=raw,
                arguments=arguments,
                error=error,
            ))
        try:
            return capability_system.run(inputs)
        finally:
            capability_system.clear_once()   # 「允许一次」只覆盖这一批


# CPU 体系对象，多体系共用
DC = CPU()
