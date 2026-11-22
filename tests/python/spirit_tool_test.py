"""真实工具循环联调：让模型调 bash，再用结果回一轮。"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-tool-")

from Engine import Engine          # noqa: E402
from Memory import mem             # noqa: E402
from Render import render          # noqa: E402
from UserInput import userinput    # noqa: E402

msgs = ["用 bash 执行 echo spirit_ok，然后告诉我输出"]
events = []
render.add_sink(events.append)


def source():
    if msgs:
        return msgs.pop(0)
    raise EOFError


userinput.set_source(source)

engine = Engine()
print("start:", engine.start())
engine.run()

print("types:", [e["type"] for e in events])
print("tool_call:", [e for e in events if e["type"] == "tool_call"])
print("tool_result:", [e for e in events if e["type"] == "tool_result"])
print("assistant:", "".join(e["text"] for e in events if e["type"] == "assistant_delta"))
print("addresses:", [r.address for r in mem.records()])
print("TOOL LOOP OK")
