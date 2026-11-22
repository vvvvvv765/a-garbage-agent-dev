"""显示体系（常驻执行流）链路测试：不调模型，直接往数据表写入。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-render-")

from Engine import Engine                      # noqa: E402
from Memory import mem, STREAM, USER, ASSISTANT, REASONING, TOOL_CALL, TOOL_OUTPUT, EXCEPTION  # noqa: E402
from Render import render                      # noqa: E402
from Bus import NT, keys                       # noqa: E402


events = []
render.add_sink(events.append)

engine = Engine()
print("start:", engine.start())
time.sleep(0.2)

# 模拟一轮写入：用户 -> 流式思考 -> 思考整段(应被跳过) -> 流式正文 -> 正文整段 -> 工具调用 -> 结果 -> 异常
mem.submit(USER, "你好")
mem.push_transient(STREAM, {"delta": "先想", "thinking": True})
mem.push_transient(STREAM, {"delta": "一下", "thinking": True})
mem.push_transient(STREAM, {"end": True, "thinking": True})
mem.submit(REASONING, {"type": "thinking", "thinking": "先想一下", "signature": "s", "_dialect": "anthropic"})
mem.push_transient(STREAM, "你")
mem.push_transient(STREAM, "好")
mem.push_transient(STREAM, {"end": True})
mem.submit(ASSISTANT, "你好")
mem.submit(TOOL_CALL, {"call_id": "c1", "name": "bash", "arguments": '{"bashinput":"echo hi"}'})
mem.submit(TOOL_OUTPUT, {"call_id": "c1", "output": "hi", "meta": {}})
mem.submit(EXCEPTION, {"system": "Test", "where": "x", "kind": "E", "message": "boom", "time": ""})

time.sleep(0.6)

types = [e["type"] for e in events]
print("live events:", types)
print("reasoning text:", "".join(e["text"] for e in events if e["type"] == "reasoning_delta"))
print("assistant text:", "".join(e["text"] for e in events if e["type"] == "assistant_delta"))
print("tool_result:", [e for e in events if e["type"] == "tool_result"])
print("exception:", [e for e in events if e["type"] == "exception"])

history = engine.history_events()
print("history types:", [e["type"] for e in history])

NT.get(keys.CPU_RENDER).action = "stop"
time.sleep(0.4)
render.shutdown()

assert "".join(e["text"] for e in events if e["type"] == "reasoning_delta") == "先想一下"
assert "reasoning" not in types, "流式已有片段时不应再整段显示思考"
assert types.index("reasoning_end") < types.index("assistant_delta"), types
assert types.count("assistant_delta") == 2, types
assert "assistant_message" not in types, "流式已有片段时不应再整段显示"
assert types[-1] == "exception" or "exception" in types
assert any(e["name"] == "bash" for e in events if e["type"] == "tool_result")
# 回放仍然保留整段思考（历史不依赖瞬态）
assert "reasoning" in [e["type"] for e in history]
print("RENDER TEST OK")
