"""上下文用量估算测试：系统提示词 / 工具定义 / 对话消息。"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Provider import adapter  # noqa: E402
from Usage import estimate_tokens  # noqa: E402

# ---------- 估算函数 ----------
assert estimate_tokens("") == 0
assert estimate_tokens("abcd") == 1
assert estimate_tokens("你好世界") == 4
assert estimate_tokens("你好abcd") == 3
print("estimate ok")

# ---------- 一次假模型请求 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-context-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-context-work-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")


def fake(handle, bundle, schemas, thinking_on, effort="medium"):
    yield NS(type="response.output_text.delta", delta="收到")
    yield NS(type="response.completed", response=NS(
        output=[],
        usage=NS(input_tokens=2000, output_tokens=5, total_tokens=2005,
                 input_tokens_details=NS(cached_tokens=0)),
    ))


original = adapter.create
adapter.create = fake
seen = []


def source():
    if seen:
        raise EOFError
    seen.append(1)
    return "只回复：收到"


try:
    engine.set_input_source(source)
    assert engine.start()
    engine.run()
finally:
    adapter.create = original

stats = engine.context()
print("context:", stats)
assert stats["system"] > 0, stats
assert stats["tools"] > 0, stats
assert stats["messages"] > 0, stats
assert stats["total"] == stats["system"] + stats["tools"] + stats["messages"], stats
assert stats["window"] == int(config.get("llm.context_window", 128000))
assert 0 < stats["percent"] < 100, stats
assert stats["total"] == 2000, stats  # 用真实 input_tokens 校准
assert stats["system"] + stats["tools"] + stats["messages"] == 2000, stats
assert stats.get("calibrated") is True, stats
assert stats is not gpu.context_stats()  # 返回副本

# ---------- Web 接口 ----------
import WebUI.server as server  # noqa: E402

server._engine = engine
api = server.test_client()
data = api.get("/api/context").get_json()
assert data["total"] == stats["total"], data
print("web context ok:", json.dumps(data, ensure_ascii=False))

print("\nCONTEXT TEST OK")
