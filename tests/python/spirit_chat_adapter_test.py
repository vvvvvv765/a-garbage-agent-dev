"""Chat Completions 适配器：消息转换 / 流事件 / 工具调用 / usage / 参数回退。"""
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Config import config  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402
from Provider.Adapter import (  # noqa: E402
    ChatAdapter,
    ResponsesAdapter,
    _to_chat_messages,
    _to_chat_tools,
    get_adapter,
)

config.set("llm.model", "test-model")

# ---------- 1. 消息转换 ----------
bundle = ContextBundle(
    instructions="系统提示",
    messages=(
        {"role": "user", "content": "读文件"},
        {"role": "assistant", "content": "我来读"},
        {"type": "function_call", "call_id": "c1", "name": "readFile",
         "arguments": '{"path":"a.txt"}'},
        {"type": "function_call_output", "call_id": "c1", "output": "hello"},
        {"role": "user", "content": "继续"},
    ),
)
messages = _to_chat_messages(bundle)
assert messages[0] == {"role": "system", "content": "系统提示"}
assert messages[1] == {"role": "user", "content": "读文件"}
assert messages[2]["role"] == "assistant"
assert messages[2]["content"] == "我来读"
assert messages[2]["tool_calls"][0]["id"] == "c1"
assert messages[2]["tool_calls"][0]["function"]["name"] == "readFile"
assert messages[3] == {"role": "tool", "tool_call_id": "c1", "content": "hello"}
assert messages[4] == {"role": "user", "content": "继续"}
print("message conversion ok")

# 没有前置 assistant 正文时，工具调用单独成一条 assistant 消息
bundle2 = ContextBundle(
    instructions="",
    messages=(
        {"role": "user", "content": "x"},
        {"type": "function_call", "call_id": "c2", "name": "listDir", "arguments": "{}"},
    ),
)
messages2 = _to_chat_messages(bundle2)
assert messages2[-1]["role"] == "assistant" and messages2[-1]["content"] is None
assert messages2[-1]["tool_calls"][0]["id"] == "c2"
print("tool-call grouping ok")

# ---------- 2. 工具 schema ----------
schemas = [
    {"type": "function", "name": "readFile", "description": "读",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
]
tools = _to_chat_tools(schemas)
assert tools[0]["type"] == "function"
assert tools[0]["function"]["name"] == "readFile"
print("tool schema conversion ok")

# ---------- 3. 流事件 ----------
chunks = [
    NS(choices=[NS(delta=NS(content="Hel"))], usage=None),
    NS(choices=[NS(delta=NS(content="lo"))], usage=None),
    NS(choices=[NS(delta=NS(reasoning_content="想一下"))], usage=None),
    NS(choices=[NS(delta=NS(tool_calls=[NS(
        index=0, id="c1",
        function=NS(name="readFile", arguments='{"path":'),
    )]))], usage=None),
    NS(choices=[NS(delta=NS(tool_calls=[NS(
        index=0, id=None,
        function=NS(name=None, arguments='"a.txt"}'),
    )]))], usage=None),
    NS(choices=[], usage=NS(prompt_tokens=11, completion_tokens=7, total_tokens=18)),
]

captured = {}


class FakeHandle:
    def create(self, **kwargs):
        captured.update(kwargs)
        return iter(chunks)


adapter = ChatAdapter()
stream = adapter.create(FakeHandle(), bundle, schemas, thinking_on=False)
events = list(stream)

assert captured["stream"] is True
assert captured["model"] == "test-model"
assert captured["messages"] == messages
assert captured["tools"] == tools
deltas = [adapter.text_delta(event) for event in events if adapter.is_text_delta(event)]
assert deltas == ["Hel", "lo"], deltas
thoughts = [adapter.thinking_delta(event) for event in events if adapter.is_thinking_delta(event)]
assert thoughts == ["想一下"], thoughts
completed = events[-1]
assert adapter.is_completed(completed)
output = list(adapter.completed_output(completed))
kinds = [adapter.item_type(item) for item in output]
assert kinds == ["reasoning", "function_call"], kinds
assert adapter.dump_reasoning(output[0])["summary"][0]["text"] == "想一下"
call = adapter.tool_call(output[1])
assert call == {"call_id": "c1", "name": "readFile", "arguments": '{"path":"a.txt"}'}
usage = adapter.usage(completed)
assert usage["input"] == 11 and usage["output"] == 7 and usage["total"] == 18, usage
print("stream events ok")

# ---------- 4. stream_options 不支持时回退一次 ----------
class FallbackHandle:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            assert "stream_options" in kwargs
            raise ValueError("Unsupported parameter: stream_options")
        assert "stream_options" not in kwargs
        return iter([NS(choices=[NS(delta=NS(content="ok"))], usage=None)])


handle = FallbackHandle()
stream = adapter.create(handle, bundle2, [], False)
events = list(stream)
assert handle.calls == 2
assert any(adapter.is_text_delta(event) for event in events)
print("stream_options fallback ok")

# ---------- 5. kind 选择 ----------
assert isinstance(get_adapter("openai-chat"), ChatAdapter)
assert isinstance(get_adapter("openai"), ResponsesAdapter)
assert isinstance(get_adapter(""), ResponsesAdapter)
print("adapter kind ok")

print("\nCHAT ADAPTER TEST OK")
