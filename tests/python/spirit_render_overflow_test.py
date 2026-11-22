"""瞬态超过 deque 上限：渲染器按绝对游标推进，不能丢尾部。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-render-overflow-")

from Engine import Engine  # noqa: E402
from Memory import mem, STREAM  # noqa: E402
from Render import render  # noqa: E402

received = []


tick = [0]


def slow(event):
    if event["type"] == "assistant_delta":
        received.append(event["text"])
        tick[0] += 1
        if tick[0] % 20 == 0:
            time.sleep(0.005)   # 每 20 段停 5ms：稳定制造“渲染落后于写入”


render.add_sink(slow)
render.set_console(False)
engine = Engine()
engine.start()
time.sleep(0.3)

for _ in range(20000):
    mem.push_transient(STREAM, {"delta": "x"})
time.sleep(1.0)              # 渲染器已开始消费这 20000 段（deque 满）
for _ in range(5999):
    mem.push_transient(STREAM, {"delta": "y"})
mem.push_transient(STREAM, {"delta": "CANARY"})
deadline = time.time() + 40
while time.time() < deadline:
    if "CANARY" in "".join(received):
        break
    time.sleep(0.5)
time.sleep(0.3)

joined = "".join(received)
print("收到:", len(received), "段 | x:", joined.count("x"), "| y:", joined.count("y"), "| CANARY:", "CANARY" in joined)
assert "CANARY" in joined, "容量溢出后尾部落丢失"
assert joined.count("y") == 5999, f"溢出后的新片段丢失：{joined.count('y')}"
# 前面的 x 允许被 deque 在渲染追赶前挤掉一部分（那是容量上限的正常行为），
# 但绝不能重复绘制：总段数不能超过实际写入数。
assert joined.count("x") > 0, "前面一个片段都没画"
assert len(received) <= 26000, f"有片段被重复绘制：{len(received)} 段"
render.shutdown()
print("\nRENDER OVERFLOW TEST OK")
