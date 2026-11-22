"""
内核侧的 worker 池（K2）：把能力放进独立进程执行。

协议：一行 JSON 请求 → 一行 JSON 响应；worker 由本进程拉起，超时 / 取消 / 崩溃时
杀整棵进程树并换一个新的。它不是安全沙箱，只是故障隔离。
"""
import atexit
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from Config import config
from Log import log
from Paths import home

CREATE_NO_WINDOW = 0x08000000
ROOT = Path(__file__).resolve().parent.parent

# 这些能力放到 worker 进程；process_* / todo_* 有内核侧状态，留在内核
WORKER_NAMES = {
    "bash",
    "readFile",
    "writeFile",
    "listDir",
    "replaceInFile",
    "searchFiles",
    "findFiles",
    "fetchUrl",
    "webSearch",
    "sessionSearch",
    "sandboxRun",
    "dnsLookup",
    "portScan",
    "httpProbe",
    "httpRequest",
    "parseData",
    "archiveList",
    "archiveExtract",
    "archiveCreate",
}


class _Worker:
    def __init__(self, sticky=""):
        self.sticky = sticky
        self.queue = queue.Queue()
        self.busy = False
        self.closed = False
        self.proc = self.__spawn()
        self.reader = threading.Thread(target=self.__read, daemon=True)
        self.reader.start()
        try:
            hello = self.queue.get(timeout=15)
        except queue.Empty:
            hello = {}
        if not hello.get("__ready__"):
            self.closed = True
            log.error("Capabilities", "能力 worker 启动失败（没有 ready 握手）")
            self.kill()

    def __spawn(self):
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--capability-worker"]
        else:
            command = [sys.executable, "-m", "Capabilities.Worker"]
        env = dict(os.environ)
        env["SPIRIT_HOME"] = str(home())
        workdir = str(config.get("engine.workdir", "") or (home() / "workspace"))
        env["SPIRIT_WORKDIR"] = workdir
        env["SPIRIT_WORKER"] = "1"
        return subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )

    def __read(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.queue.put(json.loads(line))
                except json.JSONDecodeError:
                    continue
        finally:
            self.queue.put({"__dead__": True})

    def request(self, payload, timeout, cancel=None):
        if self.closed:
            return {"ok": False, "content": "worker 已关闭"}
        try:
            self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as error:
            return {"ok": False, "dead": True, "content": f"worker 写入失败：{error}"}
        deadline = time.monotonic() + max(1.0, float(timeout))
        while True:
            if cancel is not None and cancel.is_set():
                return {"ok": False, "cancel": True, "content": "已取消"}
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"ok": False, "timeout": True,
                        "content": f"能力超时：超过 {timeout:g} 秒没有返回"}
            try:
                response = self.queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if response.get("__dead__"):
                return {"ok": False, "dead": True, "content": "能力进程异常退出"}
            if response.get("id") == payload.get("id"):
                return response

    def kill(self):
        self.closed = True
        try:
            if self.proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                        capture_output=True,
                        timeout=5,
                    )
                else:
                    try:
                        os.killpg(os.getpgid(self.proc.pid), 9)
                    except OSError:
                        self.proc.kill()
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=3)
        except Exception:
            pass


class WorkerPool:
    def __init__(self):
        self.__lock = threading.Condition()
        self.__generic = []
        self.__sticky = {}
        self.__closed = False
        self.__stats = {
            "spawns": 0, "calls": 0, "timeouts": 0,
            "cancels": 0, "kills": 0, "transport_errors": 0,
        }
        atexit.register(self.shutdown)

    # ---------- 配置 ----------
    def enabled(self):
        if os.environ.get("SPIRIT_NO_WORKERS"):
            return False
        return bool(config.get("engine.capability_isolation", False))

    def workers(self):
        try:
            return max(1, int(config.get("engine.capability_workers", 2)))
        except (TypeError, ValueError):
            return 2

    # ---------- 取 / 还 ----------
    def __spawn(self, sticky=""):
        self.__stats["spawns"] += 1
        worker = _Worker(sticky=sticky)
        if sticky:
            self.__sticky[sticky] = worker
        else:
            self.__generic.append(worker)
        return worker

    def __acquire(self, sticky, timeout, cancel=None):
        deadline = time.monotonic() + max(1.0, float(timeout))
        with self.__lock:
            while True:
                if self.__closed:
                    return None
                if sticky:
                    worker = self.__sticky.get(sticky)
                    if worker is not None and (
                        worker.closed or worker.proc.poll() is not None
                    ):
                        self.__sticky.pop(sticky, None)
                        worker = None
                    if worker is None:
                        worker = self.__spawn(sticky)
                    if worker.closed:
                        return None
                    if not worker.busy:
                        worker.busy = True
                        return worker
                else:
                    for item in list(self.__generic):
                        if item.closed or (not item.busy and item.proc.poll() is not None):
                            self.__generic = [x for x in self.__generic if x is not item]
                    free = [item for item in self.__generic if not item.busy and not item.closed]
                    if free:
                        free[0].busy = True
                        return free[0]
                    alive = [item for item in self.__generic if not item.closed]
                    self.__generic[:] = alive
                    if len(alive) < self.workers():
                        worker = self.__spawn()
                        if worker.closed:
                            return None
                        worker.busy = True
                        return worker
                if cancel is not None and cancel.is_set():
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.__lock.wait(min(0.2, remaining))

    def __release(self, worker):
        with self.__lock:
            worker.busy = False
            self.__lock.notify_all()

    def __drop(self, worker):
        with self.__lock:
            worker.busy = False
            worker.closed = True      # 先标记，锁内不会再被领走
            if worker.sticky:
                if self.__sticky.get(worker.sticky) is worker:
                    self.__sticky.pop(worker.sticky, None)
            else:
                self.__generic = [item for item in self.__generic if item is not worker]
            self.__lock.notify_all()
        worker.kill()                 # taskkill / wait 可能几秒，必须在锁外

    # ---------- 调用 ----------
    def run(self, name, arguments, execution=None):
        if not self.enabled():
            return None
        if name == "bash":
            session = getattr(execution, "session_id", "") if execution else ""
            sticky = f"shell:{session or 'primary'}"
        else:
            sticky = ""
        cancel = execution.cancel if execution is not None else None
        timeout = execution.timeout if execution is not None else 120
        worker = self.__acquire(sticky, timeout, cancel)
        if worker is None:
            return {"ok": False, "content": "执行 worker 不可用（超时或正在关闭）"}
        self.__stats["calls"] += 1
        call_id = f"w{uuid.uuid4().hex[:12]}"
        payload = {"id": call_id, "name": name, "arguments": arguments}
        try:
            response = worker.request(payload, timeout, cancel)
            if response.get("timeout"):
                self.__stats["timeouts"] += 1
            if response.get("cancel"):
                self.__stats["cancels"] += 1
            if response.get("dead") or response.get("timeout") or response.get("cancel"):
                self.__stats["kills"] += 1
                self.__drop(worker)
                return response
            return response
        except Exception as error:
            self.__stats["transport_errors"] += 1
            self.__stats["kills"] += 1
            self.__drop(worker)
            return {"ok": False, "content": f"worker 调用失败：{error}"}
        finally:
            if not worker.closed:
                self.__release(worker)

    def stats(self):
        with self.__lock:
            workers = list(self.__generic) + list(self.__sticky.values())
            return {
                "enabled": self.enabled(),
                "workers": len(workers),
                "busy": sum(1 for item in workers if item.busy),
                "pids": [item.proc.pid for item in workers],
                "sticky": list(self.__sticky),
                **self.__stats,
            }

    def shutdown(self):
        with self.__lock:
            if self.__closed:
                return
            self.__closed = True
            workers = list(self.__generic) + list(self.__sticky.values())
            self.__generic = []
            self.__sticky = {}
            self.__lock.notify_all()
        for worker in workers:
            worker.kill()
