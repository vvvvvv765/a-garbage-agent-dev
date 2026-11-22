"""K3：内核故障注入——worker 被杀 / 磁盘写失败 / 健康指标 / API。"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ.pop("SPIRIT_NO_WORKERS", None)
os.environ.pop("SPIRIT_WORKER", None)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-kf-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402
from Disk import disk  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-kf-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-kf-work-"))
(work / "a.txt").write_text("kernel-fault", encoding="utf-8")
engine = Engine(home=home, workdir=work)
config.set("engine.capability_isolation", True)
engine.set_approval("auto")
assert engine.start()


def run(name, arguments, cid):
    raw = json.dumps(arguments, ensure_ascii=False)
    return capabilities.run([CapabilityInput(cid, name, raw, arguments)])[0]


# ---------- 1. 初次调用拉起 worker，指标可见 ----------
out = run("readFile", {"path": str(work / "a.txt")}, "kf-1")
assert out.ok and "kernel-fault" in out.content, out.content
stats = capabilities.stats()
assert stats["worker"]["enabled"] is True and stats["worker"]["workers"] >= 1, stats
assert stats["worker"]["pids"], stats
print("1. worker 指标 ok:", stats["worker"]["pids"])

# ---------- 2. 外部杀 worker → 下一次调用自动恢复 ----------
pid = stats["worker"]["pids"][0]
if os.name == "nt":
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
else:
    try:
        os.kill(pid, 9)
    except OSError:
        pass
time.sleep(0.5)
recovered = None
for index in range(4):
    recovered = run("readFile", {"path": str(work / "a.txt")}, f"kf-r{index}")
    if recovered.ok:
        break
    time.sleep(0.4)
assert recovered is not None and recovered.ok, recovered.content
after = capabilities.stats()
assert after["worker"]["spawns"] >= stats["worker"]["spawns"] + 1, after
print("2. 杀 worker 后自动恢复 ok")

# 连续杀 3 次：崩溃循环也不能把池卡死
base = capabilities.stats()["worker"]["spawns"]
for round_index in range(3):
    pids = capabilities.stats()["worker"]["pids"]
    if not pids:
        run("readFile", {"path": str(work / "a.txt")}, f"kf-warm{round_index}")
        pids = capabilities.stats()["worker"]["pids"]
    target = pids[0]
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(target), "/F"], capture_output=True)
    else:
        try:
            os.kill(target, 9)
        except OSError:
            pass
    time.sleep(0.4)
    for attempt in range(3):
        result = run("readFile", {"path": str(work / "a.txt")}, f"kf-loop{round_index}-{attempt}")
        if result.ok:
            break
        time.sleep(0.3)
    assert result.ok, result.content
assert capabilities.stats()["worker"]["spawns"] >= base + 3
print("2b. 连续崩溃循环不卡池 ok")

# ---------- 3. 落盘失败：内核不崩，下一次调用照常 ----------
original = disk.artifact


def broken(*_args, **_kwargs):
    raise OSError("disk full")


disk.artifact = broken
try:
    big = run(
        "bash",
        {"command": "python -c \"print('x' * 20000)\""},
        "kf-disk",
    )
    assert not big.ok and "结果处理失败" in big.content, big.content
finally:
    disk.artifact = original

again = run("readFile", {"path": str(work / "a.txt")}, "kf-again")
assert again.ok and "kernel-fault" in again.content, again.content
print("3. 落盘失败隔离 ok")

# ---------- 4. /api/kernel ----------
from WebUI import server as web  # noqa: E402

web._engine = engine
http = web.test_client()
payload = http.get("/api/kernel").get_json()
assert payload["ok"] and "worker" in payload, payload
assert payload["cpu"]["state"] in ("idle", "waiting_model", "running_tools"), payload
assert payload["cpu"]["turn_active"] is False, payload
assert "queued" in payload, payload
print("4. /api/kernel ok")

capabilities.shutdown()
print("\nALL KERNEL FAULT TESTS PASSED")
