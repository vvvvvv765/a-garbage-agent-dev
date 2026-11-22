"""
持久 shell（能力体系内部的零件，不是能力）：同一个 bash 进程连续跑命令。

为什么需要：
  - `cd` / `export` / `source venv` 要保留；每次新起 bash 这些都会丢
  - 命令之间串行（一把锁），不改变能力池的并发

协议：
  每条命令前后打印随机标记，读到 END 标记就是这条命令结束。
  取消 / 超时会杀整棵进程树；下次调用自动重开一个新的 shell（状态丢失，文档写明）。
"""
import codecs
import os
import subprocess
import threading
import time
import uuid

from .Sandbox import sandbox

from .Executions import executions


class PersistentShell:
    def __init__(self):
        self.__lock = threading.Lock()
        self.__cond = threading.Condition()
        self.__buffer = bytearray()
        self.__overflow = False
        self.__buffer_limit = 2 * 1024 * 1024
        self.__proc = None
        self.__reader = None
        self.__closed = True
        self.__workdir = None
        self.__env = None

    def stop(self):
        proc = self.__proc
        self.__proc = None
        if proc is not None:
            try:
                executions.untrack(proc)
            except Exception:
                pass
        self.__closed = True
        if proc is not None:
            try:
                if proc.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                        capture_output=True, timeout=5,
                    )
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
        with self.__cond:
            self.__buffer.clear()
            self.__overflow = False
            self.__cond.notify_all()

    def _start(self, workdir, env):
        from .Bash import bash_path
        self.stop()
        proc = subprocess.Popen(
            [bash_path(), "-s"],
            shell=False,
            cwd=workdir,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **(dict(start_new_session=True) if os.name != "nt" else {}),
        )
        self.__proc = proc
        # 登记给执行子体系：用户点停止时能杀掉这棵 shell 进程树
        try:
            executions.track(proc)
        except Exception:
            pass
        self.__workdir = workdir
        self.__env = env
        self.__closed = False
        self.__buffer.clear()
        self.__overflow = False
        self.__reader = threading.Thread(
            target=self.__read, args=(proc,), name="PersistentShell", daemon=True
        )
        self.__reader.start()

    def __read(self, proc):
        fd = proc.stdout.fileno()
        try:
            while True:
                chunk = os.read(fd, 4096)
                if not chunk:
                    break
                with self.__cond:
                    self.__buffer.extend(chunk)
                    if len(self.__buffer) > self.__buffer_limit:
                        # 没有换行标记的巨量输出：保留开头（命令标记）和尾部，别把内存吃穿，
                        # 也不能把 begin 标记删掉（否则这一条命令永远等不到结束）
                        head = bytes(self.__buffer[:4096])
                        self.__buffer = bytearray(head) + self.__buffer[-self.__buffer_limit // 2:]
                        self.__overflow = True
                    self.__cond.notify_all()
        except Exception:
            pass
        finally:
            with self.__cond:
                # 只关掉“自己”：超时重开后，旧 reader 晚到的 finally
                # 不能把新 shell 标记成已关闭（会误报 shell 已退出）
                if self.__proc is proc:
                    self.__closed = True
                self.__cond.notify_all()

    def __ensure(self):
        if self.__proc is not None and self.__proc.poll() is None and not self.__closed:
            return
        self._start(self.__workdir, self.__env)

    def run(self, workdir, env, command, timeout=30, cancel=None, on_output=None):
        """跑一条命令；返回 (output, status, problem)。

        problem: "" / "cancelled" / "timeout" / "exited"
        """
        with self.__lock:
            if cancel is not None and cancel.is_set():
                return "", None, "cancelled"
            self.__workdir = workdir
            self.__env = env
            self.__ensure()
            if self.__proc is None:
                return "", None, "exited"

            marker = uuid.uuid4().hex
            script = (
                f"printf '\\n__SPIRIT_BEGIN_{marker}__\\n'\n"
                f"{{ {command}\n}} </dev/null\n"
                f"__spirit_status=$?\n"
                f"printf '\\n__SPIRIT_END_{marker}__ %s\\n' \"$__spirit_status\"\n"
            )
            begin = f"__SPIRIT_BEGIN_{marker}__".encode()
            end = f"__SPIRIT_END_{marker}__".encode()
            try:
                self.__proc.stdin.write(script.encode("utf-8"))
                self.__proc.stdin.flush()
            except Exception:
                self.stop()
                return "", None, "exited"

            self.__overflow = False   # 这条命令的截断标记
            deadline = time.monotonic() + max(0.1, timeout)
            problem = ""
            emitted = 0
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            while True:
                with self.__cond:
                    data = bytes(self.__buffer)
                    overflowed = self.__overflow
                    start = data.find(begin)
                    if start >= 0 and on_output is not None:
                        # 实时片段：从 BEGIN 之后到现在，只发新增的部分
                        finish_at = data.find(end, start)
                        region_end = finish_at if finish_at >= 0 else len(data)
                        payload = data[start + len(begin):region_end]
                        if len(payload) > emitted:
                            text = decoder.decode(payload[emitted:])
                            emitted = len(payload)
                            if text:
                                on_output(text)
                    if start >= 0:
                        finish = data.find(end, start)
                        if finish >= 0:
                            line_end = data.find(b"\n", finish)
                            if line_end >= 0:
                                output = data[start + len(begin):finish]
                                if overflowed:
                                    output = "[输出过大，中间已截断]\n".encode("utf-8") + output
                                status_text = data[
                                    finish + len(end):line_end
                                ].strip()
                                del self.__buffer[:line_end + 1]
                                try:
                                    status = int(status_text.decode() or "0")
                                except ValueError:
                                    status = None
                                return (
                                    output.decode("utf-8", errors="replace").strip("\n"),
                                    status,
                                    "",
                                )
                if cancel is not None and cancel.is_set():
                    problem = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    problem = "timeout"
                    break
                if self.__proc.poll() is not None or self.__closed:
                    problem = "exited"
                    break
                with self.__cond:
                    self.__cond.wait(0.05)

            # 取消 / 超时 / shell 退出：杀树，下一次自动重开
            with self.__cond:
                partial = bytes(self.__buffer).decode("utf-8", errors="replace")
                self.__buffer.clear()
            self.stop()
            partial = "\n".join(
                line for line in partial.splitlines()
                if f"__SPIRIT_BEGIN_{marker}__" not in line
                and f"__SPIRIT_END_{marker}__" not in line
            ).strip("\n")
            return partial, None, problem


shell = PersistentShell()
