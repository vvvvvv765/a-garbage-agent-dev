"""reasoning 跨方言：按产出方言过滤，不把 thinking 块塞给别的协议。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Bus import NT, keys  # noqa: E402
from Contract import ThinkingControl  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import mem  # noqa: E402
from Memory.Addresses import REASONING, USER  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-rd-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-rd-work-"))
engine = Engine(home=home, workdir=work)
NT.register(keys.CPU_THINKING, ThinkingControl(should_process=True, effort="medium"))

openai_p = engine.save_provider({"name": "O", "kind": "openai", "base_url": "https://o.test", "models": ["m"]})
anthropic_p = engine.save_provider({"name": "A", "kind": "anthropic", "base_url": "https://a.test", "models": ["m"]})

mem.clear()
mem.submit(USER, "问题")
mem.submit(REASONING, {"type": "reasoning", "id": "rs_1", "encrypted_content": "x", "_dialect": "openai"})
mem.submit(REASONING, {"type": "thinking", "thinking": "想", "signature": "sig", "_dialect": "anthropic"})
mem.submit(REASONING, {"type": "thinking", "thinking": "老记录", "signature": "sig"})   # 无方言，按形状
mem.submit(REASONING, {"type": "reasoning", "summary": [{"type": "summary_text", "text": "聊天方言"}]})  # 无方言且无 id
mem.flush()


def reasoning_in_bundle():
    bundle = gpu.build_context(compact=False)
    return [m for m in bundle.messages if isinstance(m, dict) and m.get("type") == "reasoning"] + \
           [m for m in bundle.messages if isinstance(m, dict) and m.get("type") == "thinking"]


engine.activate_provider(openai_p["id"])
items = reasoning_in_bundle()
assert len(items) == 1, items
assert items[0].get("id") == "rs_1" and "_dialect" not in items[0], items[0]
print("1. Responses 只收自己的 reasoning ok")

engine.activate_provider(anthropic_p["id"])
items = reasoning_in_bundle()
assert len(items) == 2, items
assert all(i.get("type") == "thinking" and i.get("signature") for i in items), items
assert all("_dialect" not in i for i in items), items
print("2. Anthropic 只收 thinking ok")

print("ALL REASONING DIALECT TESTS PASSED")
