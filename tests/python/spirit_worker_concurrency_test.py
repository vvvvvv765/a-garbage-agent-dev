"""WorkerPool 并发正确性：多线程 / 多请求不串响应、超时不连累其他请求。"""
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ.pop("SPIRIT_NO_WORKERS", None)
os.environ.pop("SPIRIT_WORKER", None)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-wc-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities.Executions import Execution  # noqa: E402
from Capabilities.WorkerPool import WorkerPool  # noqa: E402
from Config import config  # noqa: E402
from Paths import set_home  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-wc-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-wc-work-"))
set_home(home)
config.load()
config.set("engine.workdir", str(work))
config.set("engine.capability_isolation", True)
config.set("engine.capability_workers", 2)

files = {}
for index in range(30):
    path = work / f"f{index}.txt"
    path.write_text(f"marker-{index}", encoding="utf-8")
    files[index] = path

pool = WorkerPool()
assert pool.enabled()


def read(index):
    execution = Execution(f"read-{index}", "readFile", 20.0)
    return index, pool.run("readFile", {"path": str(files[index])}, execution)


with ThreadPoolExecutor(max_workers=20) as executor:
    results = list(executor.map(read, range(30)))

for index, response in results:
    assert response.get("ok") is True, (index, response)
    assert f"marker-{index}" in response.get("content", ""), (index, response)
print("1. 30 个并发读，响应不串 ok")


def bash(index):
    execution = Execution(f"bash-{index}", "bash", 20.0)
    return index, pool.run(
        "bash", {"command": f"echo BASH-{index}"}, execution
    )


with ThreadPoolExecutor(max_workers=5) as executor:
    results = list(executor.map(bash, range(5)))
for index, response in results:
    assert response.get("ok") is True, (index, response)
    assert f"BASH-{index}" in response.get("content", ""), (index, response)
print("2. 串行 shell 的并发调用不串 ok")

# 一个慢请求超时，不能连累后面的请求
slow = Execution("slow", "bash", 5.0)
blocked = pool.run("bash", {"command": "sleep 20"}, slow)
assert blocked.get("ok") is False and "超时" in blocked.get("content", ""), blocked
after = pool.run(
    "readFile", {"path": str(files[0])}, Execution("after", "readFile", 20.0)
)
assert after.get("ok") is True and "marker-0" in after.get("content", ""), after
print("3. 超时不连累后续请求 ok")

stats = pool.stats()
assert stats["calls"] >= 37 and stats["kills"] >= 1, stats
print("4. 统计 ok:", {k: stats[k] for k in ("spawns", "calls", "timeouts", "kills")})

pool.shutdown()
print("\nWORKER CONCURRENCY TEST PASSED")
