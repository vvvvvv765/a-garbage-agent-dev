"""批 B：spill 可读 / 工具结果就地配对 / Responses 终止兜底。"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityOutput, capabilities  # noqa: E402
from Capabilities.Sandbox import sandbox  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import mem  # noqa: E402
from Memory.Addresses import ASSISTANT, TOOL_CALL, TOOL_OUTPUT, USER  # noqa: E402
from Provider.Adapter import _ResponsesStream  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-b-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-b-work-"))
engine = Engine(home=home, workdir=work)
workdir = Path(config.get("engine.workdir"))

# ---------- 1. spill 默认落在能力产物区（数据根/Artifacts，不在工作区），模型读得回来 ----------
from Paths import artifacts_dir  # noqa: E402

big = "x" * 20000
item = SimpleNamespace(name="bash", call_id="call_big")
output = CapabilityOutput("call_big", big, True, {})
posted = capabilities._CapabilitySystem__postprocess(item, output)
path = Path(posted.meta["path"])
assert path.exists(), path
assert artifacts_dir().resolve() in path.resolve().parents, (path, artifacts_dir())
assert workdir.resolve() not in path.resolve().parents, f"框架产物不该进工作区：{path}"
assert "spill" in path.parts, path
assert path.parent.name == "spill" and path.parent.parent.name == "Artifacts", path
assert sandbox.resolve(str(workdir), str(path)) == path.resolve()
assert str(path) in posted.content
print("1. spill 可读 ok")

# ---------- 2. 缺失的工具结果就地配对（不再追加到末尾） ----------
mem.clear()
mem.submit(USER, "第一个问题")
mem.submit(ASSISTANT, "好的")
mem.submit(TOOL_CALL, {"call_id": "c1", "name": "bash", "arguments": "{}"})
mem.submit(USER, "第二个问题")
mem.flush()
bundle = gpu.build_context(compact=False)
messages = list(bundle.messages)
kinds = [m.get("type") or m.get("role") for m in messages]
call_at = next(i for i, m in enumerate(messages) if m.get("type") == "function_call")
assert call_at + 1 < len(messages), kinds
assert messages[call_at + 1].get("type") == "function_call_output", kinds
assert messages[call_at + 1].get("call_id") == "c1"
assert messages[call_at + 1].get("output") == "(工具结果缺失)"
later_user = [i for i, m in enumerate(messages) if m.get("role") == "user" and i > call_at]
assert later_user and call_at + 1 < later_user[0], kinds
print("2. 工具结果就地配对 ok")

# ---------- 3. Responses 终止兜底 ----------
class Event:
    def __init__(self, kind, item=None, response=None):
        self.type = kind
        self.item = item
        self.response = response


class Chunk:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


chat_item = SimpleNamespace(type="function_call", call_id="c9", name="readFile", arguments="{}")
incomplete = Event("response.incomplete", response=Chunk(output=[chat_item], usage={"input_tokens": 3, "output_tokens": 2}))
events = list(_ResponsesStream(iter([incomplete])))
assert events, "incomplete 应该有兜底事件"
assert events[-1].type == "response.completed"
assert events[-1].response.output and events[-1].response.output[0].call_id == "c9"
assert events[-1].response.usage["input_tokens"] == 3

# 直接断流（没有任何终止事件）也要有兜底
partial = Event("response.output_item.done", item=chat_item)
events = list(_ResponsesStream(iter([partial])))
assert events[-1].type == "response.completed"
assert events[-1].response.output[0].call_id == "c9"

# 正常 completed 原样透传，不重复
normal = Event("response.completed", response=Chunk(output=[], usage=None))
events = list(_ResponsesStream(iter([normal])))
assert len(events) == 1 and events[0] is normal
print("3. Responses 终止兜底 ok")

print("ALL PAIRING / SPILL TESTS PASSED")
