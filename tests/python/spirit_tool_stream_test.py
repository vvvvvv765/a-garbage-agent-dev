"""工具执行实时输出：能力 emit → 瞬态 → 渲染 tool_delta；最终结果仍以记录为准。"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-tool-stream-"))
work = Path(tempfile.mkdtemp(prefix="spirit-tool-stream-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402
from Capabilities.Executions import executions  # noqa: E402
from Engine import Engine  # noqa: E402
from Render import render  # noqa: E402

events = []
render.add_sink(events.append)
render.set_console(False)
engine = Engine(home=home, workdir=work)
engine.start()


class StreamCap:
    name = "stream_cap"
    description = "测试：执行中吐片段"
    parameters = {"type": "object", "properties": {}}

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters, side_effect="read")

    def run(self, arguments):
        execution = executions.current()
        execution.emit("第一段")
        time.sleep(0.05)
        execution.emit("第二段")
        return "第一段第二段"


engine.register_capability(StreamCap())
out = capabilities.run([CapabilityInput("c-stream", "stream_cap", "{}", {})])[0]
time.sleep(0.6)
deltas = [e for e in events if e["type"] == "tool_delta" and e.get("call_id") == "c-stream"]
assert "".join(e["text"] for e in deltas) == "第一段第二段", deltas
assert any(e["type"] == "tool_result" for e in events), [e["type"] for e in events]
print("1. 能力 emit → tool_delta ok")

# 真实 bash：两条输出之间隔 0.2 秒，实时片段应分两段到
events.clear()
command = "printf a; sleep 0.2; printf b"
capabilities.run([CapabilityInput(
    "c-bash", "bash",
    json.dumps({"command": command}), {"command": command},
)])
time.sleep(0.6)
text = "".join(
    e["text"] for e in events
    if e["type"] == "tool_delta" and e.get("call_id") == "c-bash"
)
assert "a" in text and "b" in text, events
print("2. bash 实时片段 ok:", repr(text))

render.shutdown()
print("\nTOOL STREAM TEST OK")
