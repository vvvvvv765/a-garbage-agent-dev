"""思考片段的接线：模型流 -> 瞬态表（thinking 标记）-> 整段落盘。"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-think-")

from Memory import mem, STREAM, ASSISTANT, REASONING  # noqa: E402
from Memory.ModO import ModOutput                     # noqa: E402
from Provider import adapter                          # noqa: E402


class FakeAdapter:
    """只按事件字典取值，验证内存体系的接线，不碰真实方言。"""

    def is_thinking_delta(self, event):
        return event["k"] == "thinking"

    def thinking_delta(self, event):
        return event["v"]

    def is_text_delta(self, event):
        return event["k"] == "text"

    def text_delta(self, event):
        return event["v"]

    def is_completed(self, event):
        return event["k"] == "done"

    def completed_output(self, event):
        return event["output"]

    @staticmethod
    def item_type(item):
        return item["type"]

    @staticmethod
    def tool_call(item):
        return item

    @staticmethod
    def dump_reasoning(item):
        return {"type": "thinking", "thinking": item["text"], "signature": "sig"}

    @staticmethod
    def usage(event):
        return None


adapter.current = lambda: FakeAdapter()   # 单元测试只测接线


events = [
    {"k": "thinking", "v": "先想"},
    {"k": "thinking", "v": "一下"},
    {"k": "text", "v": "答案"},
    {"k": "text", "v": "在这"},
    {"k": "done", "output": [{"type": "reasoning", "text": "先想一下"}]},
]

mem.clear()
calls = ModOutput().consume(iter(events), epoch=7)
assert calls == [], calls

transients = mem.transient(STREAM)
print("transients:", transients)
assert [t.get("thinking") for t in transients] == [True, True, True, None, None, None], transients
assert [t.get("delta") for t in transients] == ["先想", "一下", None, "答案", "在这", None], transients
assert transients[2] == {"end": True, "epoch": 7, "thinking": True}
assert transients[5] == {"end": True, "epoch": 7}

records = mem.records()
addresses = [record.address for record in records]
print("records:", addresses)
assert REASONING in addresses and ASSISTANT in addresses
reasoning = next(r.payload for r in records if r.address == REASONING)
assert reasoning["thinking"] == "先想一下", reasoning
assistant = next(r.payload for r in records if r.address == ASSISTANT)
assert assistant == "答案在这", assistant

print("THINKING STREAM TEST OK")
