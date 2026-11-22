"""真实一轮联调：发一句话 -> 模型回复 -> 落盘，用临时会话目录。"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-live-")

from Engine import Engine          # noqa: E402
from Memory import mem             # noqa: E402
from Render import render          # noqa: E402
from UserInput import userinput    # noqa: E402

msgs = ["只回复两个字：收到"]
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

text = "".join(e["text"] for e in events if e["type"] == "assistant_delta")
print("assistant:", repr(text))
print("addresses:", [r.address for r in mem.records()])
print("session dir files:", os.listdir(os.environ["SPIRIT_SESSION_DIR"]))
print("LIVE OK")
