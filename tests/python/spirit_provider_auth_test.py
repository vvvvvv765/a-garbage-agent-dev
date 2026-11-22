"""供应商：认证方式（x-api-key / Bearer）、Base URL 归一、错误分类、BIOS 建客户端。

对应 2026-11-19 的实战问题：opencode go 用 Responses 协议 → 405；
cc-switch 里的正确写法是 anthropic 协议 + ANTHROPIC_API_KEY（x-api-key）。
"""
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

import AgentStart.Agentstart as bios  # noqa: E402
from AgentStart import client  # noqa: E402
from Config import Providers, config  # noqa: E402
from DC import Reconnect  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-auth-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-auth-work-"))
from Engine import Engine  # noqa: E402

engine = Engine(home=home, workdir=work)

# ---------- 1. Base URL 归一 ----------
assert Providers.normalize_base("anthropic", "https://opencode.ai/zen/go/") == "https://opencode.ai/zen/go"
assert Providers.normalize_base("anthropic", "https://x.test/anthropic/v1/") == "https://x.test/anthropic"
assert Providers.normalize_base("openai", "https://api.openai.com/v1") == "https://api.openai.com/v1"
print("normalize base ok")

# ---------- 2. 保存：auth / website / /v1 被去掉 ----------
item = engine.save_provider({
    "name": "OpenCode Go",
    "kind": "anthropic",
    "auth": "key",
    "base_url": "https://opencode.ai/zen/go/v1/",   # 用户手填成带 /v1 的地址
    "website": "https://opencode.ai/go",
    "api_key": "sk-opencode-test",
    "models": ["deepseek-v4.1-flash[1M]"],
})
assert item["base_url"] == "https://opencode.ai/zen/go", item["base_url"]
assert item["auth"] == "key", item
assert item["website"] == "https://opencode.ai/go", item
engine.activate_provider(item["id"])
assert config.get("llm.auth") == "key"
assert config.get("llm.provider") == "anthropic"

# 老配置 / 没写 auth 的 anthropic 提供商：默认 token（Bearer），与 cc-switch 默认一致
legacy = engine.save_provider({
    "name": "Legacy Relay",
    "kind": "anthropic",
    "base_url": "https://relay.test",
    "api_key": "sk-legacy",
    "models": ["m"],
})
assert legacy["auth"] == "token", legacy
assert Providers._public(
    {"id": "x", "kind": "anthropic", "models": []}, None
)["auth"] == "token"
print("save + activate ok")

# ---------- 3. 探测模型：两种认证头 ----------
seen = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        seen.append({
            "path": self.path,
            "x-api-key": self.headers.get("x-api-key", ""),
            "auth": self.headers.get("Authorization", ""),
            "version": self.headers.get("anthropic-version", ""),
        })
        body = {"data": [{"id": "m1"}, {"id": "m2"}]}
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

models = Providers.probe_models(base, "k1", "anthropic", "key")
assert models == ["m1", "m2"], models
assert seen[-1]["x-api-key"] == "k1" and not seen[-1]["auth"], seen[-1]
assert seen[-1]["path"].endswith("/v1/models"), seen[-1]
assert seen[-1]["version"] == "2023-06-01", seen[-1]

seen.clear()
Providers.probe_models(base, "t1", "anthropic", "token")
assert seen[-1]["auth"] == "Bearer t1" and not seen[-1]["x-api-key"], seen[-1]

seen.clear()
Providers.probe_models(base, "o1", "openai", "key")
assert seen[-1]["auth"] == "Bearer o1", seen[-1]
print("probe models auth ok")

# ---------- 4. 真实 Anthropic SDK：路径 /v1/messages + 认证头 ----------
from anthropic import Anthropic  # noqa: E402


class MsgHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        seen.append({
            "path": self.path,
            "x-api-key": self.headers.get("x-api-key", ""),
            "auth": self.headers.get("Authorization", ""),
        })
        payload = b'{"type":"message","id":"m","role":"assistant","content":[],"model":"x","stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":0}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


msg_server = ThreadingHTTPServer(("127.0.0.1", 0), MsgHandler)
msg_port = msg_server.server_address[1]
threading.Thread(target=msg_server.serve_forever, daemon=True).start()
msg_base = f"http://127.0.0.1:{msg_port}"

def send(client_obj):
    seen.clear()
    client_obj.messages.create(model="m", max_tokens=8, messages=[{"role": "user", "content": "hi"}])
    return seen[-1]


# auth=key：只有 x-api-key，不能被环境里的 ANTHROPIC_API_KEY 顶掉
# （自己种一个环境变量当反例，不再依赖本机 Claude Code 环境恰好有 Key）
_env = __import__("os").environ
_planted = {k: _env.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
_env["ANTHROPIC_API_KEY"] = "env-planted-key"
got = send(bios._anthropic_client("k9", msg_base, "key"))
for _name, _value in _planted.items():
    if _value is None:
        _env.pop(_name, None)
    else:
        _env[_name] = _value
assert got["path"] == "/v1/messages", got
assert got["x-api-key"] == "k9", got
assert not got["auth"], got

# auth=token：Authorization: Bearer
got = send(bios._anthropic_client("t9", msg_base, "token"))
assert got["auth"] == "Bearer t9" and not got["x-api-key"], got

# 用干净环境再验一次（没有环境变量时同样只有 x-api-key）
os_env = __import__("os").environ
saved = {k: os_env.pop(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN") if k in os_env}
try:
    got = send(bios._anthropic_client("k9", msg_base, "key"))
    assert got["x-api-key"] == "k9" and not got["auth"], got
finally:
    os_env.update(saved)
# 环境变量必须原样恢复
assert saved == {k: os_env[k] for k in saved}
print("sdk url + auth header ok")

# ---------- 5. 错误分类：405 不重试，5xx 重试 ----------
class FakeError(Exception):
    def __init__(self, status, url="http://x.test/v1/messages"):
        super().__init__(f"Error code: {status}")
        self.status_code = status
        self.request = type("Req", (), {"url": url})()


r = Reconnect.Reconnect()
assert r.retryable(FakeError(405)) is False
assert r.retryable(FakeError(404)) is False
assert r.retryable(FakeError(429)) is True
assert r.retryable(FakeError(500)) is True
assert r.retryable(ConnectionResetError()) is True

text = r.describe(FakeError(405))
assert "HTTP 405" in text and "请求地址" in text, text
print("reconnect classify ok")

attempts = {"n": 0}


def boom():
    attempts["n"] += 1
    raise FakeError(405)


result = Reconnect.Reconnect(max_attempts=5, base_delay=0).chat(boom, lambda s: [])
assert not result.ok and attempts["n"] == 1, (result, attempts)
assert "405" in (result.error or ""), result.error

# ---------- 6. BIOS：auth=token 走 auth_token ----------
class StubAnthropic:
    calls = []

    def __init__(self, **kwargs):
        StubAnthropic.calls.append(kwargs)
        self.messages = object()


original = bios.Anthropic
bios.Anthropic = StubAnthropic
try:
    config.set("llm.auth", "token")
    config.set("llm.base_url", "https://opencode.ai/zen/go")
    config.set("llm.api_key", "tok-123")
    bios.client.Create()
    assert StubAnthropic.calls[-1].get("auth_token") == "tok-123", StubAnthropic.calls[-1]
    assert StubAnthropic.calls[-1].get("api_key") is None, StubAnthropic.calls[-1]

    config.set("llm.auth", "key")
    bios.client.Create()
    assert StubAnthropic.calls[-1].get("api_key") is None, StubAnthropic.calls[-1]
    assert StubAnthropic.calls[-1].get("default_headers") == {"x-api-key": "tok-123"}, StubAnthropic.calls[-1]
finally:
    bios.Anthropic = original
print("bios auth branch ok")

print("\nPROVIDER AUTH TEST OK")
