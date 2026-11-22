"""
后台进程管理（不是能力，是 process_* 能力共用的零件）

- 每个进程一条读输出的线程，按行进缓冲（不阻塞主流程）
- output 按 offset 分页，模型自己记 next_offset
- 引擎关机时 stop_all()（由 ProcessStart.dispose 触发）
- 只留最近 MAX_KEPT 个进程，避免长会话里越攒越多
"""
import subprocess
import os
import signal
import threading
import time

from .Bash import bash_path

MAX_KEPT = 20
MAX_LINES = 5000


class _Proc:
    def __init__(self, pid, command, process):
        self.id = pid
        self.command = command
        self.process = process
        self.started = time.time()
        self.finished = None
        self.lines = []
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.__read, daemon=True)
        self.thread.start()

    def __read(self):
        try:
            for line in self.process.stdout:
                with self.lock:
                    self.lines.append(line.rstrip("\n"))
                    if len(self.lines) > MAX_LINES:
                        del self.lines[:len(self.lines) - MAX_LINES]
        except Exception as error:
            with self.lock:
                self.lines.append(f"[读取输出失败：{error}]")
        finally:
            try:
                code = self.process.wait()
            except Exception:
                code = "?"
            self.finished = time.time()
            with self.lock:
                self.lines.append(f"[进程结束，退出码 {code}]")

    @property
    def running(self):
        return self.process.poll() is None

    def status(self):
        if self.running:
            return f"运行中（{int(time.time() - self.started)} 秒）"
        code = self.process.returncode
        elapsed = int((self.finished or time.time()) - self.started)
        return f"已结束（退出码 {code}，用时 {elapsed} 秒）"


class ProcessManager:
    def __init__(self):
        self.__procs = {}
        self.__order = []
        self.__next = 1
        self.__lock = threading.Lock()

    def start(self, command, cwd=None, env=None):
        process = subprocess.Popen(
            [bash_path(), "-c", command],
            shell=False,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **(dict(start_new_session=True) if os.name != "nt" else {}),
        )
        with self.__lock:
            pid = f"p{self.__next}"
            self.__next += 1
            entry = _Proc(pid, command, process)
            self.__procs[pid] = entry
            self.__order.append(pid)
            while len(self.__order) > MAX_KEPT:
                old = self.__order.pop(0)
                stale = self.__procs.pop(old, None)
                if stale is not None and stale.running:
                    try:
                        stale.process.kill()
                    except Exception:
                        pass
        return entry

    def get(self, pid):
        return self.__procs.get(pid)

    def list(self):
        with self.__lock:
            entries = [self.__procs[pid] for pid in self.__order if pid in self.__procs]
        return entries

    def kill(self, entry):
        process = entry.process
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, timeout=5,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            process.wait(timeout=3)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def stop_all(self):
        for entry in self.list():
            if entry.running:
                self.kill(entry)


processes = ProcessManager()
