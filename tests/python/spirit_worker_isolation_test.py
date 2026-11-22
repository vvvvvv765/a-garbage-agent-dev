"""K2：能力 worker 进程隔离——透明执行、超时杀进程、换新 worker。"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ.pop("SPIRIT_NO_WORKERS", None)
os.environ.pop("SPIRIT_WORKER", None)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-wi-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities.Executions import Execution  # noqa: E402
from Capabilities.WorkerPool import WorkerPool  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-wi-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-wi-work-"))
(work / "hello.txt").write_text("hello-worker", encoding="utf-8")
engine = Engine(home=home, workdir=work)
config.set("engine.capability_isolation", True)
engine.set_approval("auto")
assert engine.start()


# ---------- 1. 内核透明调度：模型看到的还是同一个结果 ----------
raw = json.dumps({"path": str(work / "hello.txt")})
out = capabilities.run([
    CapabilityInput("wi-read", "readFile", raw, json.loads(raw))
])[0]
assert out.ok and "hello-worker" in out.content, out.content
assert out.meta.get("worker") is True, out.meta
print("1. readFile 走 worker ok")

# ---------- 2. 卡死 → 杀 worker → 下一次自动换新 ----------
pool = WorkerPool()
assert pool.enabled()
execution = Execution("wi-sleep", "bash", 5.0)
started = time.time()
blocked = pool.run("bash", {"command": "sleep 10"}, execution)
elapsed = time.time() - started
assert blocked.get("ok") is False and "超时" in blocked.get("content", ""), blocked
assert elapsed < 9, elapsed
after = pool.run("bash", {"command": "echo after-kill"}, None)
assert after.get("ok") is True and "after-kill" in after.get("content", ""), after
print("2. 超时杀 worker + 自动换新 ok:", round(elapsed, 1), "s")

# ---------- 3. 关掉隔离 → 回落到内核线程，行为不变 ----------
pool.shutdown()
config.set("engine.capability_isolation", False)
engine2 = Engine(home=home, workdir=work)
assert engine2.start()
config.set("engine.capability_isolation", False)
raw = json.dumps({"path": str(work / "hello.txt")})
out = capabilities.run([
    CapabilityInput("wi-direct", "readFile", raw, json.loads(raw))
])[0]
assert out.ok and "hello-worker" in out.content, out.content
assert not out.meta.get("worker"), out.meta
print("3. 关隔离回落 ok")

capabilities.shutdown()
print("\nALL WORKER ISOLATION TESTS PASSED")
