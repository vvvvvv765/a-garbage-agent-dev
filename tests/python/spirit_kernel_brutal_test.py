"""内核暴力测试：并发读写 / bash / 超时 / 随机杀 worker / 取消风暴 / 内存 / 硬盘 / 沙箱。"""
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ.pop("SPIRIT_NO_WORKERS", None)
os.environ.pop("SPIRIT_WORKER", None)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-kb-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities.Executions import Execution  # noqa: E402
from Capabilities.WorkerPool import WorkerPool  # noqa: E402
from Config import config  # noqa: E402
from Disk import disk  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import mem  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-kb-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-kb-work-"))
engine = Engine(home=home, workdir=work)
engine.use_scenario("pentest")  # sandboxRun 只在渗透场景
config.set("engine.capability_isolation", True)
config.set("engine.capability_workers", 2)
config.set("engine.capability_queue", 256)
config.set("engine.tool_workers", 4)
engine.set_approval("auto")
assert engine.start()

for index in range(100):
    (work / f"f{index}.txt").write_text(f"mark-{index}", encoding="utf-8")


def call(name, arguments, cid):
    raw = json.dumps(arguments, ensure_ascii=False)
    return capabilities.run([CapabilityInput(cid, name, raw, arguments)])[0]


# ---------- 1. 100 个文件 / 200 次并发读 ----------
def read(index):
    amount = index % 100
    out = call("readFile", {"path": str(work / f"f{amount}.txt")}, f"read-{index}")
    return amount, out


with ThreadPoolExecutor(max_workers=50) as pool:
    results = list(pool.map(read, range(200)))
failures = [(amount, out.content) for amount, out in results if not out.ok]
assert not failures, failures[:3]
for amount, out in results:
    assert f"mark-{amount}" in out.content, (amount, out.content)
print("1. 200 次并发读 ok")

# ---------- 2. 并发 bash（同一持久 shell） ----------
def bash(index):
    return call("bash", {"command": f"echo BASH-{index}"}, f"bash-{index}")


with ThreadPoolExecutor(max_workers=20) as pool:
    results = list(pool.map(bash, range(20)))
for index, out in enumerate(results):
    assert out.ok and f"BASH-{index}" in out.content, (index, out.content)
print("2. 20 次并发 bash ok")

# ---------- 3. 超时风暴：worker 被杀 + 换新 ----------
worker_pool = WorkerPool()
assert worker_pool.enabled()
executions = [
    Execution(f"slow-{index}", "bash", 2.0) for index in range(4)
]


def slow(execution):
    return worker_pool.run("bash", {"command": "sleep 30"}, execution)


started = time.time()
with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(slow, executions))
elapsed = time.time() - started
assert all(not item.get("ok") and "超时" in item.get("content", "") for item in results), results
assert elapsed < 15, elapsed
assert worker_pool.run("bash", {"command": "echo alive"}, None).get("ok")
print("3. 超时风暴 ok:", round(elapsed, 1), "s")

# ---------- 4. 载入中随机杀 worker ----------
stop = threading.Event()
killed = []


def killer():
    while not stop.is_set():
        pids = capabilities.stats().get("worker", {}).get("pids", [])
        if pids:
            target = random.choice(pids)
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(target), "/F"], capture_output=True)
            else:
                try:
                    os.kill(target, 9)
                except OSError:
                    pass
            killed.append(target)
        time.sleep(0.05)


killer_thread = threading.Thread(target=killer, daemon=True)
killer_thread.start()


def read_during(index):
    time.sleep(0.05)   # 让随机杀 worker 有机会落在请求中间
    return call("readFile", {"path": str(work / f"f{index % 100}.txt")}, f"kd-{index}")


with ThreadPoolExecutor(max_workers=20) as pool:
    results = list(pool.map(read_during, range(100)))
stop.set()
killer_thread.join(2)
ok_count = sum(1 for out in results if out.ok)
assert ok_count >= 60, (ok_count, [out.content for out in results if not out.ok][:3])
for _ in range(3):
    sanity = call("readFile", {"path": str(work / "f0.txt")}, f"sanity-{_}")
    assert sanity.ok and "mark-0" in sanity.content, sanity.content
print("4. 随机杀 worker ok:", len(killed), "次, 成功", ok_count, "/100")

# ---------- 5. 取消风暴 ----------
cancel_results = []


def cancelled_call(index):
    cancel_results.append(call("bash", {"command": "sleep 30"}, f"cancel-{index}"))


threads = [threading.Thread(target=cancelled_call, args=(index,)) for index in range(4)]
for thread in threads:
    thread.start()
time.sleep(0.6)
capabilities.cancel_all("brutal")
for thread in threads:
    thread.join(8)
assert all(not thread.is_alive() for thread in threads), "取消风暴没有返回"
assert cancel_results and all(not out.ok for out in cancel_results), cancel_results
sanity = call("readFile", {"path": str(work / "f0.txt")}, "after-cancel")
assert sanity.ok, sanity.content
print("5. 取消风暴 ok")

# ---------- 6. 内存并发 + flush ----------
mem.clear()
start_seq = 0
errors = []


def flood(index):
    try:
        for item in range(500):
            mem.submit("user", f"flood-{index}-{item}")
    except Exception as error:  # noqa: BLE001
        errors.append(error)


threads = [threading.Thread(target=flood, args=(index,)) for index in range(8)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
mem.flush()
records = mem.records()
assert not errors, errors
seqs = [record.seq for record in records]
assert seqs == list(range(1, len(seqs) + 1)), "seq 不连续"
assert len(records) >= 4000, len(records)
print("6. 内存并发 ok:", len(records), "条")

# ---------- 7. 硬盘并发落盘 ----------
def artifact(index):
    return disk.artifact(f"brutal-{index}", f"payload-{index}", folder="brutal")


with ThreadPoolExecutor(max_workers=20) as pool:
    written = list(pool.map(artifact, range(50)))
paths = [Path(item["path"]) for item in written]
assert len(set(paths)) == 50
for index, path in enumerate(paths):
    assert path.exists() and path.read_text(encoding="utf-8") == f"payload-{index}"
print("7. 硬盘并发落盘 ok")

# ---------- 8. 并行 sandboxRun：目录互不共享 ----------
def sandbox(index):
    return call(
        "sandboxRun",
        {"command": f"pwd; echo SBOX-{index}; echo data-{index} > own.txt", "timeout": 30},
        f"sbox-{index}",
    )


with ThreadPoolExecutor(max_workers=3) as pool:
    results = list(pool.map(sandbox, range(3)))
for index, out in enumerate(results):
    assert out.ok and f"SBOX-{index}" in out.content, (index, out.content)
    assert "/work" in out.content
print("8. 并行 sandboxRun ok")

# ---------- 9. 内核最终状态：active 归零、没有永久卡死 ----------
deadline = time.time() + 10
while time.time() < deadline:
    stats = capabilities.stats()
    if stats["active"] == 0:
        break
    time.sleep(0.2)
stats = capabilities.stats()
assert stats["active"] == 0, stats
assert stats["worker"]["workers"] >= 1, stats
sanity = call("bash", {"command": "echo FINAL"}, "final")
assert sanity.ok and "FINAL" in sanity.content, sanity.content
print("9. 内核最终状态 ok:", {
    "calls": stats["calls"], "failures": stats["failures"],
    "workers": stats["worker"]["workers"], "spawns": stats["worker"]["spawns"],
    "timeouts": stats["worker"]["timeouts"], "kills": stats["worker"]["kills"],
})

worker_pool.shutdown()
capabilities.shutdown()
print("\nKERNEL BRUTAL TEST PASSED")
