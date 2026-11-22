"""
执行子体系（能力体系的子体系）：在飞调用 / 取消 / 超时 / 进程树。

分工：
  - 能力主体系：线程池、校验、结果加工
  - 执行子体系：这一次调用还在不在跑、跑了多久、要不要停、子进程归谁杀

能力怎么配合：
  - 子进程类（bash）：`executions.track(proc)` 登记；取消时这里杀整棵进程树
  - 长循环（搜索 / 翻会话 / 抓取）：循环里 `executions.check()`，取消会抛 ExecutionCancelled
  - 纯 Python 死循环：线程不能被强杀，只能等它自己走到检查点（文档里写清楚）
"""
import contextvars
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field


class ExecutionCancelled(Exception):
    """能力主动检查到取消（协作式）。"""


@dataclass
class Execution:
    call_id: str
    name: str
    timeout: float
    started_at: float = field(default_factory=time.monotonic)
    status: str = "running"
    reason: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    processes: list = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    sink: object = None      # 实时输出片段回调（能力主体系注入）
    session_id: str = ""

    @property
    def deadline(self):
        return self.started_at + self.timeout

    def elapsed(self):
        return round(time.monotonic() - self.started_at, 1)

    def emit(self, text):
        """能力把执行中的输出片段交给显示（瞬态，不落盘）。"""
        sink = self.sink
        if sink is None or not text:
            return
        try:
            sink(str(text))
        except Exception:
            pass


class Executions:
    def __init__(self):
        self.__session = contextvars.ContextVar("spirit_exec_session", default="primary")
        self.__active = {}
        self.__lock = threading.RLock()
        self.__local = threading.local()

    def use_session(self, session_id):
        return self.__session.set(str(session_id or "primary"))

    def unuse_session(self, token):
        self.__session.reset(token)

    def session_id(self):
        return self.__session.get()

    # ---------- 当前线程绑定的执行 ----------
    def bind(self, execution):
        self.__local.execution = execution

    def current(self):
        return getattr(self.__local, "execution", None)

    # ---------- 在飞表 ----------
    def create(self, call_id, name, timeout, sink=None, session_id=None):
        execution = Execution(call_id, name, float(timeout), sink=sink,
                              session_id=str(session_id or self.session_id()))
        with self.__lock:
            self.__active[call_id] = execution
        return execution

    def finish(self, call_id, status="done", reason=""):
        with self.__lock:
            execution = self.__active.pop(call_id, None)
        if execution is not None:
            execution.status = status
            execution.reason = reason
        return execution

    def snapshot(self, session_id=None):
        now = time.monotonic()
        with self.__lock:
            items = list(self.__active.values())
        if session_id is not None:
            items = [e for e in items if e.session_id == str(session_id)]
        return [
            {
                "call_id": item.call_id,
                "name": item.name,
                "elapsed": round(now - item.started_at, 1),
                "timeout": item.timeout,
                "status": item.status,
                "session_id": item.session_id,
            }
            for item in items
        ]

    # ---------- 取消 ----------
    def cancel(self, call_id, reason="用户停止"):
        with self.__lock:
            execution = self.__active.get(call_id)
        if execution is None:
            return False
        execution.reason = reason
        execution.cancel.set()
        self.__kill_all(execution)
        return True

    def cancel_all(self, reason="用户停止", session_id=None):
        with self.__lock:
            items = list(self.__active.values())
        if session_id is not None:
            items = [e for e in items if e.session_id == str(session_id)]
        for execution in items:
            execution.reason = reason
            execution.cancel.set()
        for execution in items:
            self.__kill_all(execution)
        return len(items)

    def expired(self, call_id):
        with self.__lock:
            execution = self.__active.get(call_id)
        return bool(execution is not None and time.monotonic() >= execution.deadline)

    # ---------- 协作检查 ----------
    def check(self):
        execution = self.current()
        if execution is not None and execution.cancel.is_set():
            raise ExecutionCancelled(execution.reason or "已取消")

    def sleep(self, seconds):
        """可被取消的等待；返回 False 表示被取消。"""
        execution = self.current()
        end = time.monotonic() + max(0.0, float(seconds))
        while True:
            if execution is not None and execution.cancel.is_set():
                return False
            left = end - time.monotonic()
            if left <= 0:
                return True
            time.sleep(min(0.1, left))

    # ---------- 子进程 ----------
    def track(self, process):
        execution = self.current()
        if execution is None:
            return
        with execution.lock:
            execution.processes.append(process)
        if execution.cancel.is_set():
            self.__kill_one(process)

    def untrack(self, process):
        execution = self.current()
        if execution is None:
            return
        with execution.lock:
            if process in execution.processes:
                execution.processes.remove(process)

    def kill(self, process):
        self.__kill_one(process)

    def __kill_all(self, execution):
        with execution.lock:
            processes = list(execution.processes)
        for process in processes:
            self.__kill_one(process)

    @staticmethod
    def __kill_one(process):
        try:
            if process.poll() is not None:
                return
        except Exception:
            pass
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


executions = Executions()
