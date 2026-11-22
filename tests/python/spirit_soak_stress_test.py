"""高强度承载：规模 / 并发 / 落盘一致性 / 渲染压力（合成会话，不调模型）。

判据（《Agent项目构思》§〇）：
  - 本机单轮开销随规模线性，不出现 O(n²)
  - 并发写入不丢、不重复
  - 落盘水位正确，重载后条数一致
  - 渲染在瞬态洪流下不重复绘制、不卡死
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-soak-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import mem, USER, ASSISTANT, TOOL_CALL, TOOL_OUTPUT, STREAM  # noqa: E402
from Memory.Persist import PersistSystem  # noqa: E402
from Render import render  # noqa: E402

engine = Engine()
engine.start()
render.set_console(False)
time.sleep(0.3)

# ---------- 1. 并发写入：4 线程 × 3000 ----------
def producer(tid):
    for i in range(3000):
        mem.submit(USER, f"并发-{tid}-{i}")

threads = [threading.Thread(target=producer, args=(t,)) for t in range(4)]
started = time.perf_counter()
for t in threads:
    t.start()
for t in threads:
    t.join()
mem.flush()
writes = (time.perf_counter() - started) * 1000
records = mem.records()
assert len(records) >= 12000, len(records)
assert len({r.payload for r in records}) == len(records), "并发写入出现重复"
print(f"1. 并发写入 12000 条 ok（{writes:.0f}ms）")

# ---------- 2. 规模：长会话组上下文保持线性 ----------
counter = [0]

def add_turn():
    i = counter[0]
    counter[0] += 1
    mem.submit(USER, "问题 " + "x" * 100)
    mem.submit(ASSISTANT, "回答 " + "y" * 120)
    mem.submit(TOOL_CALL, {"call_id": f"c{i}", "name": "readFile",
                           "arguments": '{"path":"a.txt"}'})
    mem.submit(TOOL_OUTPUT, {"call_id": f"c{i}", "output": "z" * 600, "meta": {}})

for _ in range(500):
    add_turn()
mem.flush()
t1 = time.perf_counter()
gpu.build_context(compact=False)
ctx1 = (time.perf_counter() - t1) * 1000
for _ in range(500):
    add_turn()
mem.flush()
t2 = time.perf_counter()
bundle = gpu.build_context(compact=False)
ctx2 = (time.perf_counter() - t2) * 1000
count = len(mem.records())
print(f"2. 组上下文：{count} 条记录 ctx1={ctx1:.1f}ms ctx2={ctx2:.1f}ms pruned={bundle.meta['pruned']}")
assert ctx2 < 1500, f"长会话组上下文太慢：{ctx2:.0f}ms"
assert ctx2 < ctx1 * 4 + 50, f"规模翻倍但耗时涨了 {ctx1:.0f}→{ctx2:.0f}ms（疑似非线性）"

# ---------- 3. 渲染洪流：不重复、不卡死 ----------
received = []
render.add_sink(lambda ev: received.append(ev.get("text")) if ev.get("type") == "assistant_delta" else None)
for i in range(30000):
    mem.push_transient(STREAM, {"delta": f"d{i}"})
time.sleep(2)
unique = len(set(received))
print(f"3. 渲染洪流：收到 {len(received)} 段，去重后 {unique} 段")
assert unique == len(received), "渲染出现重复绘制"
assert len(received) <= 30000
assert len(received) > 0

# ---------- 4. 落盘一致性：重载后条数一致 ----------
persist = PersistSystem()
before = len(mem.records())
assert persist.save() is not None
loaded_lines = sum(
    1 for line in open(persist.current_path, encoding="utf-8") if line.strip()
)
assert loaded_lines == before, f"落盘 {loaded_lines} 行 ≠ 内存 {before} 条"

mem.clear()
reloaded = PersistSystem()
reloaded.load(persist.current_path)
assert len(mem.records()) == before, f"重载 {len(mem.records())} 条 ≠ {before}"
print(f"4. 落盘一致性 ok（{before} 条，重载一致）")

render.shutdown()
print("\nSOAK STRESS TEST OK")
