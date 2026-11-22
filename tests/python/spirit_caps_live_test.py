"""真实一轮：让模型用 listDir + readFile 看看项目。"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-caps-")

from Engine import Engine          # noqa: E402
from Memory import mem             # noqa: E402
from Render import render          # noqa: E402
from UserInput import userinput    # noqa: E402

msgs = ["先 listDir 看一下当前目录，再用 readFile 读 config.json 的前 10 行，用三句话总结"]
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

print("tool calls:", [e for e in events if e["type"] == "tool_call"])
print("assistant:", "".join(e["text"] for e in events if e["type"] == "assistant_delta")[:400])
print("addresses:", [r.address for r in mem.records()])
print("CAPS LIVE OK")
