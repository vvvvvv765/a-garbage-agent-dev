"""配置界面后端测试：提供商 CRUD / 激活 / 配置里的 Key / 工作区 / 审批模式 / 接口。"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

import AgentStart.Agentstart as agentstart  # noqa: E402
from AgentStart import client as bios  # noqa: E402
from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-ui-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-ui-work-"))
(work / "marker.txt").write_text("home-work", encoding="utf-8")

engine = Engine(home=home, workdir=work)

# ---------- 提供商 ----------
state = engine.providers()
assert state["active"] == "deepseek", state
assert any(item["id"] == "deepseek" for item in state["providers"]), state

item = engine.save_provider({
    "name": "SiliconFlow",
    "base_url": "https://api.siliconflow.cn/v1",
    "api_key": "sk-test-1234",
    "models": "Qwen/Qwen2.5-72B-Instruct, deepseek-ai/DeepSeek-V3",
})
assert item["has_key"] and item["key_hint"] == "1234", item
assert item["models"] == ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-V3"]
saved = json.loads(Path(engine.config_path).read_text(encoding="utf-8"))
assert any(p["id"] == "siliconflow" and p["api_key"] == "sk-test-1234"
           for p in saved["llm"]["providers"]), saved["llm"]["providers"]
print("provider add + key in config ok")

result = engine.activate_provider("siliconflow", "Qwen/Qwen2.5-72B-Instruct")
assert result["model"] == "Qwen/Qwen2.5-72B-Instruct", result
assert config.get("llm.base_url") == "https://api.siliconflow.cn/v1"
assert config.get("llm.api_key") == "sk-test-1234"
assert engine.providers()["active"] == "siliconflow"
print("provider activate ok")

try:
    engine.delete_provider("siliconflow")
    raise AssertionError("active provider should not be deletable")
except ValueError:
    pass
engine.activate_provider("deepseek", "deepseek-Flash")
engine.delete_provider("siliconflow")
assert all(p["id"] != "siliconflow" for p in engine.providers()["providers"])
print("provider delete ok")

# ---------- Key 从配置读（BIOS） ----------
captured = {}


def fake_openai(**kwargs):
    captured.update(kwargs)
    return type("Fake", (), {"responses": "fake-responses"})()


original = agentstart.OpenAI
agentstart.OpenAI = fake_openai
try:
    config.set("llm.api_key", "sk-config-key")
    bios.Create()
    assert captured.get("api_key") == "sk-config-key", captured
finally:
    agentstart.OpenAI = original
print("BIOS reads key from config ok")

# ---------- 工作区 ----------
work2 = Path(tempfile.mkdtemp(prefix="spirit-ui-work2-"))
(work2 / "marker.txt").write_text("workspace-two", encoding="utf-8")

state = engine.add_workspace(work2, "测试工作区")
assert any(Path(item["path"]) == work2.resolve() for item in state["items"]), state
state = engine.select_workspace(work2)
assert Path(engine.workdir) == work2.resolve(), engine.workdir
output = capabilities.run([
    CapabilityInput("c-read", "readFile", '{"path":"marker.txt"}', {"path": "marker.txt"})
])[0]
assert output.ok and "workspace-two" in output.content, output.content
print("workspace add / select / capability rebind ok")

# ---------- 审批模式 ----------
engine.set_approval("auto")
assert security.mode == "auto"
saved = json.loads(Path(engine.config_path).read_text(encoding="utf-8"))
assert saved["engine"]["approval"] == "auto", saved["engine"]
engine.set_approval("rules")
print("approval mode ok")

# ---------- Web 接口 ----------
import WebUI.server as server  # noqa: E402

server._engine = engine
api = server.test_client()

assert api.get("/api/providers").get_json()["active"] == "deepseek"
added = api.post("/api/provider", json={
    "name": "Test Provider",
    "base_url": "https://example.com/v1",
    "api_key": "sk-api-9999",
    "models": ["test-model"],
}).get_json()
assert added["ok"], added
assert api.post("/api/provider/active", json={
    "id": "test-provider", "model": "test-model"
}).get_json()["ok"]
assert api.post("/api/approval-mode", json={"mode": "auto"}).get_json()["approval"] == "auto"
assert api.get("/api/settings").get_json()["approval"] == "auto"
workspaces = api.get("/api/workspaces").get_json()
assert workspaces["ok"] and workspaces["current"] == str(work2.resolve()), workspaces
assert api.post("/api/workspace/select", json={"path": str(work)}).get_json()["ok"]
assert api.post("/api/workspace", json={"path": str(work2), "name": "测试工作区"}).get_json()["ok"]
assert api.post("/api/provider", json={"bad": 1}).status_code == 400
settings = api.get("/api/settings").get_json()
assert settings["context_window"] == 128000, settings
saved = api.post("/api/settings", json={"context_window": 64000}).get_json()
assert saved["ok"] and saved["context_window"] == 64000, saved
assert api.post("/api/settings", json={"context_window": 500}).status_code == 400
api.post("/api/settings", json={"context_window": 128000})
print("web endpoints ok")

print("\nCONFIG UI TEST OK")
