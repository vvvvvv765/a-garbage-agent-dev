"""暴力测试：并发 / 沙箱 fuzz / 取消风暴 / 场景风暴 / 提供商 / Web burst / spill。"""
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
HOME = tempfile.mkdtemp(prefix="spirit-brutal-home-")
WORK = tempfile.mkdtemp(prefix="spirit-brutal-work-")
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-brutal-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC import DC  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import mem  # noqa: E402
from Paths import config_file, log_dir, session_dir  # noqa: E402

engine = Engine(home=HOME, workdir=WORK)
engine.set_approval("auto")
print("engine:", engine.scenario, "| capabilities:", len(engine.capabilities()))


def wait_until(predicate, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


# ========== 1. 沙箱路径 fuzz ==========
config.set("engine.sandbox.workspace_only", True)
engine.reload_sandbox()
evil = [
    "..\\..\\Windows\\win.ini",
    "../../etc/passwd",
    "C:\\Windows\\win.ini",
    "\\\\?\\C:\\Windows\\win.ini",
    "sub/../../outside.txt",
    "a\x00b",
    "C:" + "\\x" * 300,
]
for path in evil:
    ok, reason = capabilities.precheck("readFile", {"path": path})
    assert not ok, (path, ok, reason)
outside = Path(tempfile.mkdtemp(prefix="spirit-brutal-out-"))
(outside / "secret.txt").write_text("secret", encoding="utf-8")
assert not capabilities.precheck("readFile", {"path": str(outside / "secret.txt")})[0]
assert not capabilities.precheck("searchFiles", {"pattern": "x", "path": ".."})[0]
assert not capabilities.precheck("readFile", {"path": str(config_file())})[0]
assert not capabilities.precheck("listDir", {"path": str(session_dir())})[0]
assert not capabilities.precheck("listDir", {"path": str(log_dir())})[0]
(WORK + "/inside.txt")
Path(WORK, "inside.txt").write_text("ok", encoding="utf-8")
assert capabilities.precheck("readFile", {"path": "inside.txt"})[0]
print("sandbox path fuzz ok:", len(evil), "evil paths")

# ========== 2. 命令规则 fuzz ==========
dangerous = [
    "rm -rf /", "rm -rf ~", "sudo rm -rf --no-preserve-root /",
    "mkfs.ext4 /dev/sda", "diskpart", "format C:",
    "echo x; rm -rf /", "$(rm -rf /)",
]
for command in dangerous:
    ok, reason = capabilities.precheck("bash", {"bashinput": command})
    assert not ok, (command, reason)
for command in ["echo hi", "ls -la", "git status", "python -c 'print(1)'",
                "cd ..", "cat ../../etc/passwd", "shutdown /s /t 0"]:
    ok, reason = capabilities.precheck("bash", {"bashinput": command})
    assert ok, (command, reason)
print("command policy fuzz ok:", len(dangerous), "dangerous commands")

# ========== 3. 并发内存 ==========
start_seq = len(mem.records())


def flood(_):
    for i in range(300):
        mem.submit("user", f"stress-{_}-{i}")


threads = [threading.Thread(target=flood, args=(i,)) for i in range(8)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
mem.flush()
records = mem.records()
seqs = [record.seq for record in records]
assert seqs == list(range(1, len(seqs) + 1)), "seq not contiguous"
assert len(records) >= start_seq + 2400, len(records)
print("memory concurrency ok:", len(records), "records")

# ========== 4. 能力池并发 + 取消风暴 ==========
items = [
    CapabilityInput(f"f{i}", "bash", '{"bashinput":"echo fast"}', {"bashinput": "echo fast"})
    for i in range(40)
]
outputs = capabilities.run(items)
assert all(item.ok for item in outputs), [item.content for item in outputs if not item.ok]
print("capability pool 40 calls ok")

from Cancel import token as cancel_token  # noqa: E402

storm = {"outputs": {}, "elapsed": 0.0}


def run_sleep(index):
    started = time.time()
    output = capabilities.run([
        CapabilityInput(
            f"sleep{index}", "bash",
            '{"bashinput":"sleep 6"}', {"bashinput": "sleep 6"},
        )
    ])[0]
    storm["outputs"][index] = output
    storm["elapsed"] = max(storm["elapsed"], time.time() - started)


cancel_token.clear()
threads = [threading.Thread(target=run_sleep, args=(i,)) for i in range(6)]
for thread in threads:
    thread.start()
assert wait_until(lambda: len(capabilities.running()) >= 4, 5), capabilities.running()
time.sleep(0.3)
cancel_token.set()
cancelled = capabilities.cancel_all("暴力测试取消")
for thread in threads:
    thread.join(timeout=8)
assert all(not thread.is_alive() for thread in threads), "cancel storm did not unblock"
assert storm["elapsed"] < 5, storm["elapsed"]
outputs = list(storm["outputs"].values())
assert len(outputs) == 6, storm["outputs"]
assert all(not item.ok for item in outputs), [item.content for item in outputs]
assert any("已取消" in item.content for item in outputs)
assert capabilities.running() == [], capabilities.running()
cancel_token.clear()
print("cancel storm ok:", cancelled, "calls,", round(storm["elapsed"], 2), "s")

# ========== 5. 场景风暴 ==========
# 场景只能在会话开始前切换（前端 409 同义）；先把第 3 节灌进去的消息清掉
mem.flush()
mem.clear()
for _ in range(10):
    engine.use_scenario("pentest")
    assert engine.scenario == "pentest"
    assert DC.max_steps == 0
    engine.use_scenario("daily")
    assert engine.scenario == "daily"
    assert DC.max_steps == 0
assert len(engine.capabilities()) == 39
DC.turn_active = True
try:
    engine.use_scenario("pentest")
    raise AssertionError("turn guard failed")
except RuntimeError:
    pass
finally:
    DC.turn_active = False
print("scenario storm ok: 10 round trips")

# ========== 6. 提供商 CRUD 风暴 ==========
for i in range(15):
    item = engine.save_provider({
        "name": f"P{i}",
        "base_url": "https://example.com/v1",
        "api_key": f"sk-brutal-{i:04d}",
        "models": [f"m{i}"],
        "pricing": {"input": 1, "output": 2, "currency": "CNY"},
    })
    assert item["has_key"] and item["key_hint"] == f"{i:04d}"
state = engine.providers()
assert len(state["providers"]) == 16, len(state["providers"])
engine.activate_provider("deepseek", "deepseek-Flash")
for i in range(15):
    engine.delete_provider(f"p{i}")
assert len(engine.providers()["providers"]) == 1
print("provider CRUD storm ok: 15 add / delete")

# ========== 7. Web 接口 burst ==========
import WebUI.server as server  # noqa: E402

server._engine = engine
paths = ["/api/status", "/api/settings", "/api/usage", "/api/running",
         "/api/scenarios", "/api/providers", "/api/workspaces", "/api/history"]


def hit(_):
    client = server.test_client()
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)


with ThreadPoolExecutor(max_workers=12) as pool:
    list(pool.map(hit, range(30)))
print("web burst ok:", 30 * len(paths), "requests")

# ========== 8. 超大输出 spill ==========
class HugeCap:
    def spec(self):
        return CapabilitySpec("huge_cap", "返回 2MB", {"type": "object"}, timeout=10)

    def run(self, arguments):
        return "X" * (2 * 1024 * 1024)


capabilities.register(HugeCap())
huge = capabilities.run([CapabilityInput("c-huge", "huge_cap", "{}", {})])[0]
assert huge.ok and "已落盘" in huge.content, huge.content[:200]
spill = huge.meta.get("path")
assert spill and Path(spill).exists(), huge.meta
assert Path(spill).stat().st_size > 1_500_000
capabilities.unregister("huge_cap")
print("spill ok:", Path(spill).stat().st_size, "bytes")

# ========== 9. 引擎重复启停 ==========
for _ in range(5):
    e = Engine(home=HOME, workdir=WORK)
    e.set_input_source(lambda: (_ for _ in ()).throw(EOFError))
    assert e.start()
    e.run()
print("engine restart x5 ok")

print("\nBRUTAL TEST OK")
