"""预算剪枝的性能：长会话下组上下文必须保持线性，不能 O(n²)。

修复前实测：1000 轮（4000 条记录）组一次上下文 20 秒、2000 轮 73 秒——每剪
一条旧工具结果就把整个请求重新估算一遍（还带读提示词 / 序列化工具定义）。
修复后应当是一次线性估算 + 边剪边减。
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = tempfile.mkdtemp(prefix="spirit-budget-perf-")
os.environ["SPIRIT_HOME"] = home
os.environ["SPIRIT_SESSION_DIR"] = home

from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import mem, USER, ASSISTANT, TOOL_CALL, TOOL_OUTPUT  # noqa: E402
from Render import render  # noqa: E402

engine = Engine()
engine.start()
render.set_console(False)
time.sleep(0.2)

TURNS = 1000
for i in range(TURNS):
    mem.submit(USER, "问题 " + "x" * 100)
    mem.submit(ASSISTANT, "回答 " + "y" * 120)
    mem.submit(TOOL_CALL, {"call_id": f"c{i}", "name": "readFile",
                           "arguments": '{"path":"a.txt"}'})
    mem.submit(TOOL_OUTPUT, {"call_id": f"c{i}", "output": "z" * 600, "meta": {}})
mem.flush()

started = time.perf_counter()
bundle = gpu.build_context(compact=False)
elapsed = (time.perf_counter() - started) * 1000
print(f"records={len(mem.snapshot())} pruned={bundle.meta['pruned']} build_context={elapsed:.1f}ms")

assert len(mem.snapshot()) == TURNS * 4
assert bundle.meta["pruned"] > 0, "这组数据应当触发剪枝"
assert elapsed < 1500, f"长会话组上下文太慢：{elapsed:.0f}ms（修复前约 20 秒）"

# 再跑一次，确认不是首次初始化开销
started = time.perf_counter()
gpu.build_context(compact=False)
elapsed2 = (time.perf_counter() - started) * 1000
print(f"second build_context={elapsed2:.1f}ms")
assert elapsed2 < 1500, elapsed2

render.shutdown()
print("\nGPU BUDGET PERF TEST OK")
