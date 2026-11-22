"""思考档位：DeepSeek low/high/max 在三种方言里的参数映射与回退。"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_HOME"] = tempfile.mkdtemp(prefix="spirit-levels-home-")
os.environ["SPIRIT_SESSION_DIR"] = os.environ["SPIRIT_HOME"]

from Config import config  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402
from Provider import Adapter as ad  # noqa: E402
from WebUI import server as web  # noqa: E402


class Handle:
    def __init__(self, error=None):
        self.kwargs = []
        self.error = error

    def create(self, **kwargs):
        self.kwargs.append(dict(kwargs))
        if self.error is not None and len(self.kwargs) == 1:
            raise self.error
        return iter(())


class Reject(Exception):
    status_code = 400


def bundle():
    return ContextBundle("", ())


def deepseek():
    config.set("llm.providers", [])
    config.set("llm.provider_id", "deepseek")
    config.set("llm.base_url", "https://api.deepseek.com")
    config.set("llm.model", "deepseek-flash")


def claude():
    config.set("llm.providers", [])
    config.set("llm.provider_id", "anthropic")
    config.set("llm.base_url", "https://api.anthropic.com")
    config.set("llm.model", "claude-test")


# 1. Responses：开启/关闭 + 等级 + 旧别名
deepseek()
for thinking, effort, expected in (
    (False, "high", "none"),
    (True, "low", "low"),
    (True, "medium", "high"),
    (True, "high", "high"),
    (True, "max", "max"),
):
    h = Handle()
    ad._RESPONSES.create(h, bundle(), [], thinking, effort)
    assert h.kwargs[0]["reasoning"]["effort"] == expected, (thinking, effort, h.kwargs)
print("1. responses levels ok")

# 2. Chat：关闭时必须显式 disabled；开启带 thinking + reasoning_effort
h = Handle()
ad._CHAT.create(h, bundle(), [], False, "high")
kw = h.kwargs[0]
assert kw["extra_body"]["thinking"] == {"type": "disabled"}, kw
assert "reasoning_effort" not in kw, kw

h = Handle()
ad._CHAT.create(h, bundle(), [], True, "max")
kw = h.kwargs[0]
assert kw["extra_body"]["thinking"] == {"type": "enabled"}, kw
assert kw["reasoning_effort"] == "max", kw
print("2. chat toggle/effort ok")

# 2b. Chat 端点不认 thinking：去掉 thinking 后保留 reasoning_effort
h = Handle(Reject("thinking is not supported"))
ad._CHAT.create(h, bundle(), [], True, "low")
assert len(h.kwargs) == 2, h.kwargs
assert "thinking" not in (h.kwargs[1].get("extra_body") or {}), h.kwargs
assert h.kwargs[1]["reasoning_effort"] == "low", h.kwargs
print("2b. chat fallback ok")

# 3. DeepSeek 的 Anthropic 兼容层：开关 + output_config.effort
deepseek()
h = Handle()
ad._ANTHROPIC.create(h, bundle(), [], True, "high")
kw = h.kwargs[0]
assert kw["thinking"] == {"type": "enabled"}, kw
assert kw["extra_body"]["output_config"]["effort"] == "high", kw

h = Handle()
ad._ANTHROPIC.create(h, bundle(), [], False, "high")
kw = h.kwargs[0]
assert kw["thinking"] == {"type": "disabled"}, kw
assert "extra_body" not in kw, kw
print("3. deepseek anthropic format ok")

# 4. 真 Claude：budget_tokens 档位
claude()
h = Handle()
ad._ANTHROPIC.create(h, bundle(), [], True, "max")
kw = h.kwargs[0]
assert kw["thinking"]["budget_tokens"] == 32768, kw["thinking"]
assert kw["max_tokens"] >= 32768 + 1024, kw
h = Handle()
ad._ANTHROPIC.create(h, bundle(), [], False, "high")
assert "thinking" not in h.kwargs[0], h.kwargs
print("4. claude budgets ok")

# 5. Web 设置：旧 medium 归一为 high
assert web._normalize_effort("medium") == "high"
assert web._normalize_effort("minimal") == "low"
assert web._normalize_effort("ultra") == "max"
assert web._normalize_effort("bogus") == "high"
print("5. effort normalization ok")

print("\nTHINKING LEVELS TEST OK")
