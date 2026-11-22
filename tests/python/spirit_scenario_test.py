"""场景层测试：提示词增量 / 能力子集 / 默认值 / 轮次边界 / 接口。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

import Scenarios  # noqa: E402
from Capabilities import capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC import DC  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import _instructions  # noqa: E402

# ---------- 1. 场景包读取 ----------
items = {item["id"]: item for item in Scenarios.list_scenarios()}
assert {"daily", "pentest"} <= set(items), items
assert "日常" in items["daily"]["name"] or items["daily"]["name"] == "日常"
assert "工作方式" in Scenarios.prompt_for("daily")
assert "授权" in Scenarios.prompt_for("pentest")
print("scenario packs ok:", list(items))

# ---------- 2. 默认场景与提示词叠加 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-scenario-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-scenario-work-"))
engine = Engine(home=home, workdir=work)
assert engine.scenario == "daily", engine.scenario
assert len(engine.capabilities()) == 39, engine.capabilities()
prompt = _instructions()
assert "agent 计算机" in prompt and "# 日常场景" in prompt, prompt[:200]
names = [item["name"] for item in capabilities.schemas()]
assert "browser" in names, names
assert "sandboxRun" not in names and "portScan" not in names, names
print("default daily + prompt composition ok")

# ---------- 3. 切换场景 ----------
result = engine.use_scenario("pentest")
assert result["current"] == "pentest"
assert config.get("engine.scenario") == "pentest"
assert int(config.get("engine.max_steps")) == 0
assert DC.max_steps == 0, DC.max_steps
prompt = _instructions()
assert "渗透测试场景" in prompt and "agent 计算机" in prompt
assert "日常场景" not in prompt
assert len(engine.capabilities()) == 39
names = [item["name"] for item in capabilities.schemas()]
assert "browser" in names and "sandboxRun" in names, names
print("switch to pentest ok")

# ---------- 4. 轮次中间禁止切换 ----------
DC.turn_active = True
try:
    engine.use_scenario("daily")
    raise AssertionError("switch during turn should fail")
except RuntimeError as error:
    print("turn guard ok:", error)
finally:
    DC.turn_active = False

# ---------- 5. 能力子集真的会停 ----------
capabilities.apply_scenario(["readFile"])
names = [item["name"] for item in capabilities.schemas()]
assert names == ["readFile"], names
engine.use_scenario("daily")
assert len(capabilities.schemas()) == 26
print("capability subset ok")

# ---------- 6. Web 接口 ----------
import WebUI.server as server  # noqa: E402

server._engine = engine
api = server.test_client()
state = api.get("/api/scenarios").get_json()
assert state["ok"] and state["current"] == "daily", state
switched = api.post("/api/scenario", json={"id": "pentest"}).get_json()
assert switched["ok"] and switched["current"] == "pentest", switched
assert api.get("/api/settings").get_json()["scenario"] == "pentest"
DC.turn_active = True
blocked = api.post("/api/scenario", json={"id": "daily"})
assert blocked.status_code == 409, blocked.status_code
DC.turn_active = False
assert api.post("/api/scenario", json={"id": "daily"}).get_json()["ok"]
assert api.post("/api/scenario", json={"id": "nope"}).status_code == 400
print("web scenario endpoints ok")

print("\nSCENARIO TEST OK")
