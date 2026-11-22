"""token 估算缓存：第二次组上下文不能再调用 estimate_tokens（工具记录也必须命中）。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-token-cache-"))
work = Path(tempfile.mkdtemp(prefix="spirit-token-cache-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

import GPU.core as G  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import ASSISTANT, TOOL_CALL, TOOL_OUTPUT, USER, mem  # noqa: E402
from Render import render  # noqa: E402

render.set_console(False)
engine = Engine(home=home, workdir=work)
engine.start()

for index in range(60):
    mem.submit(USER, "请检查这个目录 " * 40)
    mem.submit(ASSISTANT, "好的，我先列出文件。 " * 40)
    mem.submit(TOOL_CALL, {
        "call_id": f"cc{index}",
        "name": "bash",
        "arguments": '{"command":"ls -la"}',
    })
    mem.submit(TOOL_OUTPUT, {
        "call_id": f"cc{index}",
        "output": "file listing line\n" * 300,
        "meta": {},
    })
mem.flush()

calls = {"n": 0}
original = G.estimate_tokens


def counting(text):
    calls["n"] += 1
    return original(text)


G.estimate_tokens = counting

first_bundle = G.gpu.build_context(compact=False)
assert first_bundle.messages, "上下文为空，测不到估算"
first_calls = calls["n"]
assert first_calls > 0, "首次构建没有调用估算"
print("1. 首次构建估算调用", first_calls, "次，缓存", len(G._TOKEN_CACHE), "条")

calls["n"] = 0
second_bundle = G.gpu.build_context(compact=False)
assert len(second_bundle.messages) == len(first_bundle.messages), "两次上下文条数不一致"
assert calls["n"] == 0, f"第二次构建仍在重新估算 {calls['n']} 次（工具记录缓存键没命中）"
print("2. 第二次构建零重新估算 ok")

# 追加一条新记录：只该估算新增的那一条
calls["n"] = 0
mem.submit(USER, "继续")
mem.flush()
third = G.gpu.build_context(compact=False)
assert len(third.messages) >= len(second_bundle.messages)
assert calls["n"] <= 1, f"新增一条却重算了 {calls['n']} 次"
print("3. 增量记录只估算新增 ok")

render.shutdown()
print("\nTOKEN CACHE TEST OK")
