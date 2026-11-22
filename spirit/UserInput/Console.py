"""
控制台输入：进程里唯一读 stdin 的地方（用户输入体系的子模块）

为什么要“唯一”：
  用户消息和审批回答都来自同一个 stdin。两处各自 input() 时，行缓冲会把
  用户先敲的消息交给审批、或把审批答案当成下一条消息。这里只留一个读线程，
  按“读到这一行时有没有待审批”路由：
    有 pending 审批 → 这一行是审批答案
    没有           → 用户消息队列 → UserInput.uim()（仍由 CPU 线程取）

  用户输入：read(prompt)         → 阻塞等消息队列
  控制台审批：ask(request)        → 阻塞等 pending 答案，返回 (allowed, reason)

不 import 任何体系；由主板把 console.read 接给 UserInput、console.ask 接给审批出口。
读线程只搬原始行，不写数据表、不发指令；写内存的 uim() 仍在 CPU 线程上。
"""
import queue
import threading
import time
from concurrent.futures import Future, TimeoutError as FutureTimeout


class _Cancelled:
    """审批被叫醒（停止 / 关机 / EOF），不是用户回答。"""

    def __init__(self, reason):
        self.reason = str(reason or "已取消")


_EOF = object()


class Console:
    def __init__(self):
        self.__messages = queue.Queue()
        self.__lock = threading.Lock()
        self.__pending = None          # (call_id, Future)
        self.__closed = False
        self.__discard_until = 0.0
        self.__reading = False
        self.__prompt = ""
        self.__started = False
        self.__thread = None

    # ---------- 生命周期 ----------
    def start(self, reader=None):
        """启动唯一读线程。reader 可注入（测试用）：fn() -> 一行 / None=EOF。"""
        with self.__lock:
            if self.__started:
                return
            self.__started = True
        self.__thread = threading.Thread(
            target=self.__loop,
            args=(reader,),
            name="console-reader",
            daemon=True,
        )
        self.__thread.start()

    def close(self):
        """关机：挂起的审批按拒绝收，消息队列放 EOF 哨兵。"""
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            self.__drain_locked()
            self.__messages.put(_EOF)
            pending = self.__pending
        if pending is not None and not pending[1].done():
            pending[1].set_result(_Cancelled("控制台已关闭"))

    # ---------- 路由状态（信号处理 / 前端用） ----------
    @property
    def asking(self):
        with self.__lock:
            return self.__pending is not None

    @property
    def reading(self):
        with self.__lock:
            return self.__reading

    def queued(self):
        """还没取走的用户消息数（诊断 / 测试）。"""
        return self.__messages.qsize()

    def discard_next(self, seconds=5.0):
        """Ctrl+C：作废接下来一行（限时，避免很久以后误伤）。"""
        with self.__lock:
            self.__discard_until = time.monotonic() + max(0.0, float(seconds))

    # ---------- 用户输入源 ----------
    def read(self, prompt=""):
        """阻塞取一行用户消息；控制台关闭 / EOF 时抛 EOFError。

        注意：EOF 之前已经排队的消息会先读完（粘性 EOF 排在队尾），
        这样 `printf 'exit\\n' | spirit` 不会把最后一行丢掉。
        """
        self.start()
        with self.__lock:
            self.__reading = True
            self.__prompt = prompt
        try:
            if prompt:
                print(prompt, end="", flush=True)
            item = self.__messages.get()
        finally:
            with self.__lock:
                self.__reading = False
                self.__prompt = ""
        if item is _EOF:
            self.__messages.put(_EOF)      # 粘性：以后再读也还是 EOF
            raise EOFError
        return item

    # ---------- 审批 ----------
    def ask(self, request, timeout=300):
        """控制台审批：返回 (allowed, reason)。

        request 用 Security 给的字段（name / arguments / untrusted / source / call_id）。
        同一时刻只允许一条 pending；重入直接抛错，暴露装配错误。
        """
        self.start()
        future = Future()
        call_id = str(request.get("call_id", "") or "")
        with self.__lock:
            if self.__closed:
                return False, "控制台已关闭，按拒绝处理"
            if self.__pending is not None:
                raise RuntimeError("同一时刻只能有一条控制台审批")
            self.__pending = (call_id, future)

        self.__print_request(request)
        try:
            try:
                answer = future.result(timeout=max(0.1, float(timeout)))
            except FutureTimeout:
                future.cancel()
                print("\n       （审批超时，按拒绝处理）", flush=True)
                return False, "审批超时，按拒绝处理"
        finally:
            with self.__lock:
                if self.__pending is not None and self.__pending[1] is future:
                    self.__pending = None

        if isinstance(answer, _Cancelled):
            return False, answer.reason
        if answer is None:
            return False, "输入结束，按拒绝"
        text = str(answer).strip().lower()
        allowed = text in {"y", "yes", "是", "允许", "allow"}
        return allowed, "用户允许" if allowed else "用户拒绝执行该能力"

    def cancel_pending(self, reason="用户停止"):
        """叫醒挂起的审批（停止 / 中断 / 关机）。"""
        with self.__lock:
            pending = self.__pending
        if pending is not None and not pending[1].done():
            pending[1].set_result(_Cancelled(reason))

    # ---------- 读线程 ----------
    def __loop(self, reader):
        while True:
            try:
                line = self.__readline(reader)
            except EOFError:
                self.__on_eof()
                return
            except KeyboardInterrupt:
                # 控制台把 Ctrl+C 也可能丢给正在读的线程；别让它把读线程打死
                continue
            self.__route(line)

    @staticmethod
    def __readline(reader):
        if reader is not None:
            line = reader()
            if line is None:
                raise EOFError
            return line
        return input()

    def __route(self, line):
        line = str(line).rstrip("\r\n")
        reprompt = ""
        with self.__lock:
            if self.__closed:
                return
            discard = False
            if self.__discard_until:
                deadline = self.__discard_until
                self.__discard_until = 0.0
                if time.monotonic() <= deadline:
                    discard = True
                    if self.__reading:
                        reprompt = self.__prompt
            if not discard:
                pending = self.__pending
                if pending is not None and not pending[1].done():
                    pending[1].set_result(line)
                else:
                    self.__messages.put(line)
        if reprompt:
            print()
            print(reprompt, end="", flush=True)

    def __on_eof(self):
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            # 不丢已排队的消息：EOF 哨兵放队尾，read 先读消息再读 EOF
            self.__messages.put(_EOF)
            pending = self.__pending
        if pending is not None and not pending[1].done():
            pending[1].set_result(_Cancelled("输入结束，按拒绝"))

    def __drain_locked(self):
        try:
            while True:
                self.__messages.get_nowait()
        except queue.Empty:
            pass

    @staticmethod
    def __print_request(request):
        print()
        print(f"[审批] {request.get('name', '')}")
        if request.get("untrusted"):
            print(
                "       ⚠ 上一条工具结果来自不可信来源"
                f"（{request.get('source', '工具')}），可能是提示注入诱导"
            )
        arguments = request.get("arguments", "")
        if arguments:
            print(f"       {arguments}")
        print("       允许执行？[y/N] ", end="", flush=True)


console = Console()
