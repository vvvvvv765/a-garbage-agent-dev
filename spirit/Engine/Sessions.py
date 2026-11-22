"""会话运行时：每个额外会话一套独立的 Memory / 总线 / 渲染 / GPU / 落盘 / CPU。

默认会话仍走 Engine 里的全局单例（CLI / 旧测试不受影响）；这里只承载
“同时开着的其他会话”。线程入口会把 Memory / 总线 / 取消令牌绑定到
contextvars，能力线程池会 copy_context，因此工具结果写回各自会话。
"""
import queue
import threading
from pathlib import Path

from Bus.NeutralTable import NeutralTable, default_table
from Cancel import CancelToken
from DC.CPU import CPU
from DC.Security import Security
from Capabilities.Executions import executions
from GPU.core import GPURender
from Memory.Memory import Memory
from Memory.Persist import PersistSystem
from Render.Render import Renderer
from UserInput.Input import User
from Bus import keys
from Capabilities.System import CapabilityScope, unuse_scope, use_scope
import Cancel as cancel_module
import Memory.Memory as memory_module
import Bus.NeutralTable as bus_module
import Scenarios


class SessionRuntime:
    def __init__(self, manager, path=None, title=""):
        self.manager = manager
        self.id = f"session-{id(self):x}"
        self.path = str(path or "")
        self.title = str(title or "新会话")
        # 场景在会话创建时快照：主会话之后换场景不影响这条会话
        self.__scenario = str(getattr(manager, "scenario", "") or Scenarios.DEFAULT_SCENARIO)
        self.capability_scope = CapabilityScope(
            Scenarios.capabilities_for(self.__scenario) or ()
        )

        self.memory = Memory()
        self.persist = PersistSystem(self.memory)
        self.memory.persist = self.persist
        self.bus = NeutralTable(parent=default_table())
        self.cancel = CancelToken()
        self.security = Security()
        self.security.set_side_effect_resolver(self.manager.capability_side_effect)
        self.security.set_approver(self.manager.approver_for(self))

        self.gpu = GPURender(self.memory, self.bus, scenario=lambda: self.scenario)
        self.render = Renderer(self.memory, self.bus, self.id)
        self.render.set_console(False)
        self.input = User(self.memory, self.bus)
        self.inbox = queue.Queue()
        self.input.set_source(self.inbox.get)

        self.lock = threading.RLock()
        self.bus.register(keys.SESSION_LOCK, self.lock, replace=True)

        self.cpu = CPU(
            memory=self.memory, bus=self.bus, security_=self.security,
            cancel=self.cancel, session_id=self.id, owns_capabilities=False,
        )
        self.cpu.attach(
            gpu=self.gpu, memory=self.memory, input_source=self.input,
            switch_provider=self.manager.switch_provider,
        )
        self.thread = None
        self.started = False
        self.manager.attach_session_sink(self)

    # ---------- 生命周期 ----------
    def start(self):
        if self.started:
            return
        self.started = True
        self.render.start()
        self.thread = threading.Thread(
            target=self.__loop, name=f"spirit-{self.id}", daemon=True
        )
        self.thread.start()

    def __loop(self):
        mem_token = memory_module.use(self.memory)
        bus_token = bus_module.use(self.bus)
        cancel_token = cancel_module.use(self.cancel)
        exec_token = executions.use_session(self.id)
        scope_token = use_scope(self.capability_scope)
        try:
            self.cpu.boot()
            self.cpu.run()
        finally:
            try:
                self.render.shutdown()
            finally:
                unuse_scope(scope_token)
                executions.unuse_session(exec_token)
                cancel_module.unuse(cancel_token)
                bus_module.unuse(bus_token)
                memory_module.unuse(mem_token)

    def stop(self):
        self.cpu.start = False
        self.cpu.interrupt()
        try:
            self.inbox.put_nowait({"text": "", "images": []})
        except Exception:
            pass

    # ---------- 输入 / 状态 ----------
    def send(self, text, images=None):
        self.start()
        self.inbox.put({"text": str(text or ""), "images": list(images or [])})

    def load(self, path):
        self.persist.load(path)
        self.path = str(path)
        self.title = self.persist.title or Path(path).stem
        self.__scenario = self.persist.scenario or Scenarios.DEFAULT_SCENARIO
        self.capability_scope.set(Scenarios.capabilities_for(self.__scenario) or ())
        return self

    @property
    def current_path(self):
        return self.persist.current_path or self.path

    @property
    def display_title(self):
        return self.persist.title or self.memory.title_hint() or self.title or "新会话"

    @property
    def scenario(self):
        return self.__scenario

    def set_scenario(self, name):
        """会话自己的场景：只改本会话的提示词 / 能力白名单，不动全局配置。"""
        item = Scenarios.get_scenario(name)
        if item is None:
            raise ValueError(f"没有这个场景：{name}")
        if self.memory.last_seq() > 0:
            raise RuntimeError("会话已经开始，场景不能再切换；新建会话时再选")
        self.__scenario = item["id"]
        self.capability_scope.set(Scenarios.capabilities_for(item["id"]) or ())
        self.persist.set_scenario(item["id"])
        return item

    @property
    def running(self):
        return bool(self.cpu and self.cpu.turn_active)

    @property
    def queue_size(self):
        return self.inbox.qsize()

    def history(self, limit_turns=40):
        from Memory.Addresses import USER as USER_ADDRESS

        try:
            limit = max(1, min(int(limit_turns), 500))
        except (TypeError, ValueError):
            limit = 40
        records = self.memory.snapshot()
        user_positions = [
            index for index, record in enumerate(records)
            if record.address == USER_ADDRESS
        ]
        if self.memory.records_floor() > 0 and len(user_positions) < limit:
            disk = self.persist.read_records(limit_turns=limit)
            if disk:
                by_seq = {record.seq: record for record in disk}
                for record in records:
                    by_seq.setdefault(record.seq, record)
                records = [by_seq[seq] for seq in sorted(by_seq)]
                user_positions = [
                    index for index, record in enumerate(records)
                    if record.address == USER_ADDRESS
                ]
        start = user_positions[-limit] if len(user_positions) > limit else 0
        return {
            "events": self.render.history(records[start:]),
            "has_more": start > 0,
            "limit": limit,
        }

    def usage(self):
        from Config import config
        from Config import Providers
        from Usage import report as usage_report

        self.memory.flush()
        budgets = {
            key: config.get(f"engine.{key}", 0) or 0
            for key in ("max_turn_tokens", "max_session_tokens",
                        "max_turn_cost", "max_session_cost")
        }
        return usage_report(
            self.memory.view("usage"),
            window=Providers.active_value(config, "context_window", 128000),
            budgets=budgets,
            last_user=self.memory.last_seq("user"),
        )

    def context(self):
        token = use_scope(self.capability_scope)
        try:
            return self.gpu.context_stats()
        finally:
            unuse_scope(token)
