"""transcript 纯读：默认不触发摘要、不写 SUMMARY；显式 compact 才压缩。"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

import GPU.core as gpu_core  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU import gpu  # noqa: E402
from Memory import ASSISTANT, SUMMARY, USER, mem  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-transcript-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-transcript-work-"))
engine = Engine(home=home, workdir=work)

# 小窗口 + 超过预算的多轮对话，保证“如果允许压缩就一定会压”
config.set("llm.context_window", 100)
# per-provider 窗口优先：把当前提供商的窗口也压小，才会触发压缩
from Config import Providers  # noqa: E402
_items = Providers.providers_of(config)
_items[0]["context_window"] = 100
config.set("llm.providers", _items)
config.set("engine.budget_ratio", 0.8)
config.set("engine.keep_recent_turns", 2)
config.set("engine.summarize", True)
def fill():
    mem.flush()
    mem.clear()
    for index in range(3):
        mem.submit(USER, f"user-{index}-" + "u" * 400)
        mem.submit(ASSISTANT, f"assistant-{index}-" + "a" * 400)
    mem.flush()


fill()

calls = {"n": 0}
original = gpu_core.summary.summarize


def fake_summarize(messages):
    calls["n"] += 1
    return "这是一段摘要"


gpu_core.summary.summarize = fake_summarize
try:
    before = len(mem.view(SUMMARY))

    # 默认只读：不摘要、不写表
    messages = engine.transcript()
    assert messages, "transcript 返回空"
    assert calls["n"] == 0, f"transcript 触发了摘要 {calls['n']} 次"
    assert len(mem.view(SUMMARY)) == before, "transcript 写了 SUMMARY"

    # 显式 compact=True 才允许摘要（换一份干净的内存，避免已有摘要挡住压缩）
    fill()
    calls["n"] = 0
    engine.transcript(compact=True)
    assert calls["n"] == 1, calls["n"]
    assert len(mem.view(SUMMARY)) == 1, len(mem.view(SUMMARY))
    assert mem.view(SUMMARY)[-1].payload.get("text") == "这是一段摘要"

    # 真实出包路径（默认 compact）仍然会压缩
    fill()
    calls["n"] = 0
    bundle = gpu.build_context()
    assert calls["n"] == 1, calls["n"]
    assert bundle.meta.get("summarized") is True, bundle.meta
finally:
    gpu_core.summary.summarize = original
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

print("transcript pure-read ok")
print("\nTRANSCRIPT TEST OK")
