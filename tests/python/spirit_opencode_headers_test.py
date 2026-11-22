"""OpenCode Go 网关要求：自己的 User-Agent + 稳定的 x-opencode-session。

对应 2026-11-19 实战报错：`400 MissingSessionID`（opencode.ai/zen/go/v1/messages）。
照抄 cc-switch 4.0 的 fallback（src-tauri/src/proxy/forwarder/opencode.rs）。
"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import Providers, config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402
from Provider import Adapter as ad_mod  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-oc-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-oc-work-"))
engine = Engine(home=home, workdir=work)

# ---------- 1. 主机识别 ----------
assert Providers.is_opencode("https://opencode.ai/zen/go")
assert Providers.is_opencode("https://opencode.ai")
assert Providers.is_opencode("https://api.opencode.ai/x")
assert not Providers.is_opencode("https://api.deepseek.com")
assert not Providers.is_opencode("https://notopencode.ai")
print("1. 主机识别 ok")

# ---------- 2. 会话 id：同一会话稳定，换会话会变 ----------
def bundle(first_user, instructions="系统提示"):
    return ContextBundle(
        instructions=instructions,
        messages=(
            {"role": "user", "content": first_user},
            {"role": "assistant", "content": "好"},
        ),
    )

one = ad_mod._opencode_session(bundle("帮我扫这个站"))
two = ad_mod._opencode_session(bundle("帮我扫这个站", instructions="换了一版系统提示"))
other = ad_mod._opencode_session(bundle("完全不同的会话"))
assert one == two, "同一会话（系统提示变了）id 必须稳定"
assert one != other, "不同会话 id 要分开"
assert one.startswith("spirit-") and len(one) == len("spirit-") + 32
assert ad_mod._opencode_session(ContextBundle(instructions="", messages=())) == "spirit-session"

# 注入前缀（运行时快照 / 项目上下文 / 摘要）不算用户消息：id 不能跟着它们变
def prefixed(runtime, text):
    return ContextBundle(instructions="sys", messages=(
        {"role": "user", "content": "当前运行时上下文（覆盖之前的快照）：" + chr(10) + runtime},
        {"role": "user", "content": "[项目上下文]" + chr(10) + "某个项目"},
        {"role": "user", "content": text},
        {"role": "assistant", "content": "好"},
    ))

one = ad_mod._opencode_session(prefixed("工作目录 A", "帮我扫这个站"))
two = ad_mod._opencode_session(prefixed("工作目录 B / 今天 2026-11-20", "帮我扫这个站"))
other = ad_mod._opencode_session(prefixed("工作目录 A", "完全不同的会话"))
assert one == two, "换运行时前缀不该改会话 id"
assert one != other, "换会话要换 id"
print("2b. 跳过注入前缀 ok")
print("2. 会话 id 稳定 ok")

# ---------- 3. 三个方言都把头带上（且非 opencode 时不带） ----------
class FakeHandle:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return object()


def capture(create):
    handle = FakeHandle()
    try:
        create(handle)
    except Exception:
        pass   # 解析器的包装可能对空流不满意，这里只看 kwargs
    return handle.kwargs or {}


b = bundle("你好")
opencode_item = engine.save_provider({
    "name": "OpenCode Go",
    "kind": "anthropic",
    "auth": "key",
    "base_url": "https://opencode.ai/zen/go",
    "api_key": "sk-test",
    "models": ["claude-haiku-5-5"],
})
engine.activate_provider(opencode_item["id"])
assert config.get("llm.base_url") == "https://opencode.ai/zen/go"

expected_session = ad_mod._opencode_session(b)
for name, create in (
    ("responses", lambda h: ad_mod._RESPONSES.create(h, b, [], False)),
    ("chat", lambda h: ad_mod._CHAT.create(h, b, [], False)),
    ("anthropic", lambda h: ad_mod._ANTHROPIC.create(h, b, [], False)),
):
    kw = capture(create)
    extra = kw.get("extra_headers") or {}
    assert extra.get("User-Agent", "").startswith("Spirit/"), (name, extra)
    assert extra.get("x-opencode-session") == expected_session, (name, extra)
    print(f"3.{name} extra_headers ok")

# 切回普通供应商 → 不该带
plain = engine.save_provider({
    "name": "DeepSeek", "kind": "anthropic", "base_url": "https://api.deepseek.com",
    "api_key": "sk-test", "models": ["m"],
})
engine.activate_provider(plain["id"])
kw = capture(lambda h: ad_mod._ANTHROPIC.create(h, b, [], False))
assert "extra_headers" not in kw, kw
print("4. 非 opencode 不带头 ok")

# ---------- 4. 模型探测 / 测速 / 测试连接也带头 ----------
seen = {}


class FakeClient:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url, headers=None):
        seen["headers"] = dict(headers or {})
        raise RuntimeError("stop-here")


real_client = Providers._http.Client
Providers._http.Client = FakeClient
try:
    try:
        Providers.check("https://opencode.ai/zen/go")
    except Exception:
        pass
    headers = seen.get("headers") or {}
    assert headers.get("User-Agent", "").startswith("Spirit/"), headers
    assert headers.get("x-opencode-session"), headers
finally:
    Providers._http.Client = real_client
print("5. 探测请求带头 ok")

print("ALL OPENCODE HEADER TESTS PASSED")
