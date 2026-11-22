"""跨进程恢复测试：write 一轮 -> 新进程 read 回放。"""
import os
import sys

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Engine import Engine          # noqa: E402
from Render import render          # noqa: E402
from UserInput import userinput    # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "read"

if mode == "write":
    prompt = sys.argv[2] if len(sys.argv) > 2 else "暗号：蓝鲸"
    msgs = [prompt]

    def source():
        if msgs:
            return msgs.pop(0)
        raise EOFError

    userinput.set_source(source)
    engine = Engine()
    print("start:", engine.start())
    engine.run()
    print("WROTE:", os.environ["SPIRIT_SESSION_DIR"])
else:
    engine = Engine()
    print("start:", engine.start())
    events = engine.history_events()
    render.shutdown()
    print("history:", [(e["type"], str(e.get("text", ""))[:20]) for e in events])
    print("RESUME OK")
