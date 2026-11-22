"""供应商：kind / 复制 / 模型探测 / BIOS 句柄选择。"""
import json
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

import AgentStart.Agentstart as bios  # noqa: E402
from AgentStart import client  # noqa: E402
from Bus import NT, keys  # noqa: E402
from Config import Providers, config  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-provider-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-provider-work-"))
engine = Engine(home=home, workdir=work)

# ---------- 1. kind + 复制 ----------
item = engine.save_provider({
    "name": "Kimi",
    "kind": "openai-chat",
    "base_url": "https://api.moonshot.cn/v1",
    "api_key": "sk-kimi-test",
    "models": ["kimi-a", "kimi-b"],
    "pricing": {"input": 1, "output": 2, "currency": "CNY"},
})
assert item["kind"] == "openai-chat", item
engine.activate_provider(item["id"])
assert config.get("llm.provider") == "openai-chat", config.get("llm.provider")

copy = engine.duplicate_provider(item["id"])["provider"]
assert copy["name"].endswith(" copy"), copy
assert copy["kind"] == "openai-chat"
raw = next(entry for entry in Providers.providers_of(config) if entry["id"] == copy["id"])
assert raw["api_key"] == "sk-kimi-test", raw
assert raw["models"] == ["kimi-a", "kimi-b"]
print("kind + duplicate ok")

# ---------- 2. 模型探测（本地 HTTP） ----------
seen = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        seen["path"] = self.path
        seen["auth"] = self.headers.get("Authorization", "")
        if self.path == "/v1/models":
            body = {"data": [{"id": "m2"}, {"id": "m1"}]}
            self.send_response(200)
        elif self.path == "/models":
            body = {"models": [{"id": "m3"}]}
            self.send_response(200)
        elif self.path == "/bad/v1/models":
            body = {"error": "unauthorized"}
            self.send_response(401)
        elif self.path == "/empty/v1/models":
            body = {}
            self.send_response(200)
        else:
            body = {"error": "not found"}
            self.send_response(404)
        payload = json.dumps(body).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    base = f"http://127.0.0.1:{port}"
    models = Providers.probe_models(base, "sk-test")
    assert models == ["m2", "m1"], models   # 保留厂商返回顺序
    assert seen["path"] == "/v1/models", seen
    assert seen["auth"] == "Bearer sk-test", seen

    models = Providers.probe_models(base + "/v1", "sk-test")
    assert models == ["m2", "m1"], models   # 保留厂商返回顺序
    assert seen["path"] == "/v1/models", seen  # 不重复拼 /v1/v1

    try:
        Providers.probe_models(base + "/bad", "sk-test")
        raise AssertionError("401 没有报错")
    except ValueError as error:
        assert "401" in str(error), error

    try:
        Providers.probe_models(base + "/empty", "sk-test")
        raise AssertionError("空列表没有报错")
    except ValueError as error:
        assert "没有模型" in str(error) or "失败" in str(error), error

    try:
        Providers.probe_models(base, "")
        raise AssertionError("空 Key 没有报错")
    except ValueError as error:
        assert "API Key" in str(error), error

    local = engine.save_provider({
        "name": "本地 Probe",
        "kind": "openai-chat",
        "base_url": base,
        "api_key": "sk-test",
        "models": ["m1"],
    })
    via_engine = engine.probe_models({
        "id": local["id"],
        "base_url": base,
        "api_key": "",
    })
    assert via_engine == ["m2", "m1"], via_engine

    # 换了地址就不复用已存 Key，避免把 Key 发到任意端点
    try:
        engine.probe_models({
            "id": local["id"],
            "base_url": base + "/other",
            "api_key": "",
        })
        raise AssertionError("换了 Base URL 仍复用了已存 Key")
    except ValueError as error:
        assert "API Key" in str(error), error
    print("probe models ok")
finally:
    server.shutdown()
    server.server_close()

# ---------- 3. BIOS 按 kind 选句柄 ----------
class FakeOpenAI:
    def __init__(self, **_kwargs):
        self.responses = NS(kind="responses")
        self.chat = NS(completions=NS(kind="chat"))


class FakeAnthropic:
    def __init__(self, **_kwargs):
        self.messages = NS(kind="anthropic")


config.set("llm.api_key", "sk-any")
config.set("llm.api_key_env", "")
original = bios.OpenAI
original_anthropic = bios.Anthropic
bios.OpenAI = FakeOpenAI
bios.Anthropic = FakeAnthropic
try:
    engine.activate_provider(item["id"])   # Kimi：openai-chat
    client.Create()
    assert NT.get(keys.LLM).kind == "chat", NT.get(keys.LLM)

    engine.activate_provider("deepseek")   # 旧配置合成的 DeepSeek：openai
    client.Create()
    assert NT.get(keys.LLM).kind == "responses", NT.get(keys.LLM)

    claude = engine.save_provider({
        "name": "Claude",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com",
        "api_key": "sk-ant-test",
        "models": ["claude-test"],
    })
    engine.activate_provider(claude["id"])
    client.Create()
    assert NT.get(keys.LLM).kind == "anthropic", NT.get(keys.LLM)
finally:
    bios.OpenAI = original
    bios.Anthropic = original_anthropic
print("bios handle ok")

shutil.rmtree(home, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)

print("\nPROVIDER MODELS TEST OK")
