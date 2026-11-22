"""整段校正 / 轮次计数：assistant_final 带全文、跨轮不串账。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-final-")

from Bus import NT, keys  # noqa: E402
from Contract import Instruction  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import mem, STREAM, ASSISTANT  # noqa: E402
from Render import render  # noqa: E402

events = []
render.add_sink(events.append)
render.set_console(False)
engine = Engine()
engine.start()
time.sleep(0.3)

control = NT.get(keys.CPU_RENDER)


def start(seq):
    control.push(Instruction(target="render", action="start", seq=seq))


def stop(seq):
    control.push(Instruction(target="render", action="stop", seq=seq))
    time.sleep(0.4)


# ---------- 1. 流式一轮：结束用整段校正 ----------
start(1)
mem.push_transient(STREAM, {"delta": "你", "epoch": 1})
mem.push_transient(STREAM, {"delta": "好", "epoch": 1})
mem.push_transient(STREAM, {"end": True, "epoch": 1})
mem.submit(ASSISTANT, "你好")
time.sleep(0.8)
types = [e["type"] for e in events]
assert types.count("assistant_delta") == 2, types
assert "assistant_message" not in types, types
final = next(e for e in events if e["type"] == "assistant_final")
assert final["text"] == "你好", final
assert types.index("assistant_final") < types.index("assistant_end"), types
stop(1)
print("1. 流式 + 整段校正 ok")

# ---------- 2. 下一轮没有流：必须出现整段消息 ----------
events.clear()
start(2)
mem.submit(ASSISTANT, "整段回复")
time.sleep(0.8)
types = [e["type"] for e in events]
assert "assistant_message" in types, types
assert "assistant_final" not in types, types
stop(2)
print("2. 跨轮不串账 ok")

# ---------- 3. 结束标记没配上记录（stop 抢先）也不能污染下一轮 ----------
events.clear()
start(3)
mem.push_transient(STREAM, {"end": True, "epoch": 3})
time.sleep(0.3)
stop(3)
start(4)
mem.submit(ASSISTANT, "第四轮")
time.sleep(0.8)
types = [e["type"] for e in events]
assert "assistant_message" in types, types
stop(4)
print("3. 错位计数不污染下一轮 ok")

render.shutdown()
print("\nRENDER FINAL TEST OK")
