"""Anthropic Messages 适配器：消息/工具/thinking signature/SSE 翻译/usage。"""
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Config import config  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402
from Provider.Adapter import (  # noqa: E402
    AnthropicAdapter,
    ResponsesAdapter,
    _to_anthropic_messages,
    _to_anthropic_tools,
    get_adapter,
)

config.set("llm.providers", [])
config.set("llm.model", "claude-test")
config.set("llm.provider_id", "anthropic")
config.set("llm.base_url", "https://api.anthropic.com")
config.set("llm.max_tokens", 8192)

# ---------- 1. 消息转换 ----------
bundle = ContextBundle(
    instructions="系统提示",
    messages=(
        {"role": "user", "content": "读文件"},
        {"role": "assistant", "content": "我来读"},
        {"type": "function_call", "call_id": "c1", "name": "readFile",
         "arguments": '{"path":"a.txt"}'},
        {"type": "function_call_output", "call_id": "c1", "output": "hello"},
        {"type": "thinking", "thinking": "先想一下", "signature": "sig-1"},
        {"role": "assistant", "content": "继续"},
    ),
)
messages = _to_anthropic_messages(bundle)
assert messages[0] == {
    "role": "user",
    "content": [{"type": "text", "text": "读文件"}],
}
assistant = messages[1]
assert assistant["role"] == "assistant"
assert assistant["content"][0] == {"type": "text", "text": "我来读"}
assert assistant["content"][1]["type"] == "tool_use"
assert assistant["content"][1]["id"] == "c1"
assert assistant["content"][1]["input"] == {"path": "a.txt"}
assert messages[2]["role"] == "user"
assert messages[2]["content"][0] == {
    "type": "tool_result", "tool_use_id": "c1", "content": "hello",
}
assert messages[3]["role"] == "assistant"
assert messages[3]["content"][0] == {
    "type": "thinking", "thinking": "先想一下", "signature": "sig-1",
}
assert messages[3]["content"][1] == {"type": "text", "text": "继续"}
print("message conversion ok")

# 多个 tool_result 合进同一条 user 消息
bundle2 = ContextBundle(
    instructions="",
    messages=(
        {"role": "user", "content": "x"},
        {"type": "function_call", "call_id": "a", "name": "f", "arguments": "{}"},
        {"type": "function_call", "call_id": "b", "name": "g", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "a", "output": "A"},
        {"type": "function_call_output", "call_id": "b", "output": "B"},
    ),
)
messages2 = _to_anthropic_messages(bundle2)
assert len(messages2) == 3, messages2
assert [b["type"] for b in messages2[1]["content"]] == ["tool_use", "tool_use"]
assert [b["tool_use_id"] for b in messages2[2]["content"]] == ["a", "b"]
print("tool grouping ok")

# 没有 signature 的旧思考块不回传
bundle3 = ContextBundle(
    instructions="",
    messages=(
        {"role": "user", "content": "x"},
        {"type": "thinking", "thinking": "旧思考", "signature": ""},
        {"role": "assistant", "content": "答"},
    ),
)
messages3 = _to_anthropic_messages(bundle3)
assert all(
    block.get("type") != "thinking"
    for message in messages3 for block in message["content"]
), messages3
print("unsigned thinking dropped ok")

# ---------- 2. 工具 schema ----------
tools = _to_anthropic_tools([
    {"type": "function", "name": "readFile", "description": "读",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
])
assert tools == [{
    "name": "readFile",
    "description": "读",
    "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}},
}]
print("tool schema ok")

# ---------- 3. SSE 事件 ----------
def usage_event(**fields):
    return NS(**fields)


events = [
    NS(type="message_start", message=NS(usage=usage_event(
        input_tokens=5, output_tokens=1,
        cache_creation_input_tokens=2, cache_read_input_tokens=3,
    ))),
    NS(type="content_block_start", index=0,
       content_block=NS(type="thinking", thinking="")),
    NS(type="content_block_delta", index=0,
       delta=NS(type="thinking_delta", thinking="先想")),
    NS(type="content_block_delta", index=0,
       delta=NS(type="signature_delta", signature="sig-1")),
    NS(type="content_block_stop", index=0),
    NS(type="content_block_start", index=1,
       content_block=NS(type="text", text="")),
    NS(type="content_block_delta", index=1,
       delta=NS(type="text_delta", text="你好")),
    NS(type="content_block_stop", index=1),
    NS(type="content_block_start", index=2,
       content_block=NS(type="tool_use", id="toolu_1", name="readFile", input={})),
    NS(type="content_block_delta", index=2,
       delta=NS(type="input_json_delta", partial_json='{"path":')),
    NS(type="content_block_delta", index=2,
       delta=NS(type="input_json_delta", partial_json='"a.txt"}')),
    NS(type="content_block_stop", index=2),
    NS(type="message_delta", delta=NS(stop_reason="tool_use"),
       usage=usage_event(output_tokens=7)),
    NS(type="message_stop"),
]

captured = {}


class FakeHandle:
    def create(self, **kwargs):
        captured.update(kwargs)
        return iter(events)


adapter = AnthropicAdapter()
stream = adapter.create(FakeHandle(), bundle2, [], thinking_on=True, effort="high")
received = list(stream)

assert captured["stream"] is True
assert captured["model"] == "claude-test"
assert captured["max_tokens"] >= 2048
assert captured["thinking"]["type"] == "enabled"
assert captured["thinking"]["budget_tokens"] < captured["max_tokens"]
assert captured["messages"] == messages2
deltas = [adapter.text_delta(e) for e in received if adapter.is_text_delta(e)]
assert deltas == ["你好"], deltas
thoughts = [adapter.thinking_delta(e) for e in received if adapter.is_thinking_delta(e)]
assert thoughts == ["先想"], thoughts
completed = received[-1]
assert adapter.is_completed(completed)
output = list(adapter.completed_output(completed))
kinds = [adapter.item_type(item) for item in output]
assert kinds == ["reasoning", "function_call"], kinds
reasoning = adapter.dump_reasoning(output[0])
assert reasoning == {"type": "thinking", "thinking": "先想", "signature": "sig-1"}
call = adapter.tool_call(output[1])
assert call["call_id"] == "toolu_1"
assert call["name"] == "readFile"
assert call["arguments"] == '{"path":"a.txt"}'
usage = adapter.usage(completed)
assert usage["input"] == 10 and usage["cached"] == 3, usage
assert usage["output"] == 7 and usage["total"] == 17, usage
print("sse translation ok")

# ---------- 4. kind 选择 ----------
assert isinstance(get_adapter("anthropic"), AnthropicAdapter)
assert isinstance(get_adapter("openai"), ResponsesAdapter)
print("adapter kind ok")

print("\nANTHROPIC ADAPTER TEST OK")
