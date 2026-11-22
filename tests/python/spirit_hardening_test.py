"""批 E：工具增量拼装 / 方言参数回退 / 预算下限 / 回切主家 / 坏配置不炸 / 日志脱敏。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from Log import log  # noqa: E402
from Paths import log_dir  # noqa: E402
from Provider import Adapter as ad_mod  # noqa: E402
from Turn import turn  # noqa: E402
from Config import Providers  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402
from DC.Failover import failover  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-hard-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-hard-work-"))
engine = Engine(home=home, workdir=work)

# ---------- 1. Chat 工具增量：没有 index 也不串 ----------
class Func:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class Tool:
    def __init__(self, index=None, id=None, function=None):
        self.index = index
        self.id = id
        self.function = function


class Delta:
    def __init__(self, tool_calls=None, content=None, finish_reason=None):
        self.tool_calls = tool_calls
        self.content = content
        self.reasoning_content = None


class Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class Chunk:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


chunks = [
    Chunk([Choice(Delta(tool_calls=[Tool(index=None, id="c1", function=Func("readFile", '{"pa'))]))]),
    Chunk([Choice(Delta(tool_calls=[Tool(index=None, id="c1", function=Func(None, 'th":"a"}'))]))]),
    Chunk([Choice(Delta(tool_calls=[Tool(index=None, id="c2", function=Func("bash", "{}"))]))]),
    Chunk([Choice(Delta(), finish_reason="stop")]),
]
events = list(ad_mod._ChatStream(iter(chunks)))
completed = events[-1]
calls = [i for i in completed.response.output if i.type == "function_call"]
assert len(calls) == 2, calls
assert calls[0].call_id == "c1" and calls[0].arguments == '{"path":"a"}', calls[0].__dict__
assert calls[1].call_id == "c2"
assert completed.truncated is False
print("1. Chat 工具增量 ok")

# 完全没 id 也不能撞成同一 call_0
anon = list(ad_mod._ChatStream(iter([
    Chunk([Choice(Delta(tool_calls=[Tool(function=Func("a", "{}"))]))]),
    Chunk([Choice(Delta(tool_calls=[Tool(function=Func("b", "{}"))]))]),
])))
ids = [i.call_id for i in anon[-1].response.output if i.type == "function_call"]
assert len(set(ids)) == len(ids) == 2, ids
print("1b. 无 id 不撞号 ok")

# finish_reason=length → truncated
length_case = list(ad_mod._ChatStream(iter([Chunk([Choice(Delta(content="x"), finish_reason="length")])])))
assert length_case[-1].truncated is True
print("1c. 截断标记 ok")

# ---------- 2. 参数被拒时回退一次 ----------
class Reject(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status_code = status


class Handle:
    def __init__(self, error):
        self.error = error
        self.kwargs = []

    def create(self, **kwargs):
        self.kwargs.append(dict(kwargs))
        if len(self.kwargs) == 1 and self.error:
            raise self.error
        class Empty:
            def __iter__(self): return iter(())
            def close(self): pass
        return Empty()


h = Handle(Reject("unsupported parameter: stream_options"))
ad_mod._CHAT.create(h, ContextBundle("", ()), [], False)
assert len(h.kwargs) == 2 and "stream_options" not in h.kwargs[1], h.kwargs

h = Handle(Reject("reasoning is not supported"))
ad_mod._RESPONSES.create(h, ContextBundle("", ()), [], False)
# 拒绝时先降到 low，不能静默删掉（DeepSeek 默认 high）
assert len(h.kwargs) == 2 and h.kwargs[1]["reasoning"]["effort"] == "low", h.kwargs
print("2. 方言参数回退 ok")

# ---------- 3. Anthropic 思考预算下限 ----------
config.set("llm.max_tokens", 1024)
config.set("llm.providers", [])
config.set("llm.model", "claude-test")
config.set("llm.provider_id", "anthropic")
config.set("llm.base_url", "https://api.anthropic.com")
h = Handle(None)
ad_mod._ANTHROPIC.create(h, ContextBundle("", ()), [], True, "high")
kw = h.kwargs[0]
assert kw["thinking"]["budget_tokens"] >= 1024, kw["thinking"]
assert kw["max_tokens"] >= kw["thinking"]["budget_tokens"] + 1024, kw
print("3. 思考预算下限 ok")

# ---------- 4. 熔断后的新轮次回切主家 ----------
a = engine.save_provider({"name": "A", "base_url": "https://a.test", "models": ["m"], "in_failover_queue": True})
b = engine.save_provider({"name": "B", "base_url": "https://b.test", "models": ["m"], "in_failover_queue": True})
config.set("engine.failover.enabled", True)
engine.activate_provider(b["id"])
failover.reset()
failover.note_origin(a["id"])
failover.record(a["id"], True)         # A 已恢复
switched = []
class FakeGPU:
    calls = 0
    def request(self): self.calls += 1; return object()
class FakeMem:
    def last_seq(self, address=None): return 0
    def consume(self, *args, **kwargs): return []
    def flush(self): pass
    def records_after(self, mark): return []

from DC import CPU as cpu_mod  # noqa: E402
cpu = cpu_mod.CPU()
cpu.attach(gpu=FakeGPU(), memory=FakeMem(), input_source=object(),
           switch_provider=lambda pid: switched.append(pid) or True)
from DC.Reconnect import AttemptResult, reconnect  # noqa: E402
real = reconnect.chat
reconnect.chat = lambda fetch, consume: AttemptResult(True, [])
try:
    turn.begin()
    cpu._CPU__ask_model()
finally:
    reconnect.chat = real
assert switched and switched[0] == a["id"], switched
print("4. 回切主家 ok")

# ---------- 5. 坏配置值不再让导入期炸 ----------
bad_home = Path(tempfile.mkdtemp(prefix="spirit-hard-bad-"))
(bad_home / "config.json").write_text(
    '{"engine": {"max_steps": "abc", "tool_workers": "x", "capability_timeout": "oops"}}',
    encoding="utf-8",
)
bad = Engine(home=bad_home, workdir=work)
assert bad is not None
print("5. 坏配置值不炸 ok")

# ---------- 6. 日志脱敏 ----------
config.set("llm.api_key", "sk-hardening-123456")
log.info("Test", "key=sk-hardening-123456 should be masked")
log_file = Path(log_dir()) / "spirit.log"
content = log_file.read_text(encoding="utf-8", errors="replace")
assert "sk-hardening-123456" not in content, "日志里还有明文 Key"
assert "***" in content
print("6. 日志脱敏 ok")

print("ALL HARDENING TESTS PASSED")
