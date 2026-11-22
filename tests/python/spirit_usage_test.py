"""上下文真实性：真实 usage / 成本 / 预算硬停 / 重复调用拦截。"""
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
from DC.Guard import guard  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import EXCEPTION, USAGE, mem  # noqa: E402
from Memory.Persist import persist  # noqa: E402
from Provider import adapter  # noqa: E402
from Usage import record, report  # noqa: E402


def reset_memory():
    mem.flush()
    mem.clear()
    persist.reset()


def usage_event(input_tokens=1000, output_tokens=200, cached=400):
    usage = NS(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_tokens_details=NS(cached_tokens=cached),
        output_tokens_details=NS(reasoning_tokens=0),
    )
    return NS(
        type="response.completed",
        response=NS(output=[], usage=usage),
    )


def make_engine(prefix, restore=False):
    home = Path(tempfile.mkdtemp(prefix=f"spirit-{prefix}-home-"))
    work = Path(tempfile.mkdtemp(prefix=f"spirit-{prefix}-work-"))
    engine = Engine(home=home, workdir=work)
    engine.set_approval("auto")
    config.set("engine.restore", restore)
    return engine


def run_turn(engine, fake):
    original = adapter.create
    adapter.create = fake
    seen = []

    def source():
        if seen:
            raise EOFError
        seen.append(1)
        return "测试一轮"

    try:
        engine.set_input_source(source)
        assert engine.start()
        engine.run()
    finally:
        adapter.create = original


# ---------- 1. 计价函数 ----------
item = record({"input": 1000, "output": 200, "cached": 400}, "chat",
              pricing={"input": 2, "output": 8})
# uncached 600*2 + cached 400*2 + output 200*8 = 3600 / 1e6
assert item["cost"] == 0.0036, item
assert item["priced"] is True and item["total"] == 1200
print("pricing ok:", item["cost"])

# ---------- 2. 真实 usage 进账本 ----------
reset_memory()
engine = make_engine("usage")


def fake_text(handle, bundle, schemas, thinking_on, effort="medium"):
    yield NS(type="response.output_text.delta", delta="收到")
    yield usage_event(1000, 200, 400)


run_turn(engine, fake_text)
reset_backup = None
data = engine.usage()
assert data["session"]["requests"] == 1, data["session"]
assert data["session"]["total"] == 1200, data["session"]
assert data["session"]["input"] == 1000 and data["session"]["output"] == 200
assert data["session"]["cached"] == 400
assert data["last"]["purpose"] == "chat"
assert config.get("llm.pricing", {}).get("input", 0) == 0  # 没配价格 -> 不计价
assert data["session"]["priced"] is False
print("usage recorded ok:", data["session"]["total"], "tokens")

# 配了价格就该算钱
reset_memory()
engine = make_engine("usage-priced")
config.set("llm.pricing", {"input": 2, "output": 8, "currency": "CNY"})
run_turn(engine, fake_text)
data = engine.usage()
assert data["session"]["priced"] is True and data["session"]["cost"] == 0.0036, data["session"]
print("cost ok:", data["session"]["cost"])

# ---------- 3. 预算硬停（工具循环里，不再请求第二次） ----------
reset_memory()
engine = make_engine("budget")
config.set("llm.pricing", {"input": 2, "output": 8, "currency": "CNY"})
config.set("engine.max_turn_tokens", 500)
calls = {"n": 0}
target = (Path(engine.workdir) / "target.txt")
target.write_text("hello", encoding="utf-8")


def fake_tool(handle, bundle, schemas, thinking_on, effort="medium"):
    calls["n"] += 1
    item = NS(
        type="function_call", call_id=f"c{calls['n']}", name="readFile",
        arguments=json.dumps({"path": "target.txt"}),
    )
    yield NS(type="response.completed", response=NS(
        output=[item],
        usage=NS(input_tokens=600, output_tokens=100, total_tokens=700,
                 input_tokens_details=NS(cached_tokens=0)),
    ))


run_turn(engine, fake_tool)
assert calls["n"] == 1, calls  # 第一次 600 就超 500，工具后不再问模型
mem.flush()
exceptions = [r.payload for r in mem.records() if r.address == EXCEPTION]
assert any("预算" in str(item.get("message", "")) for item in exceptions), exceptions[-3:]
print("budget hard stop ok, model calls:", calls["n"])

# ---------- 4. 重复调用拦截 ----------
guard.reset()
results = [guard.repeated("bash", '{"bashinput":"echo 1"}') for _ in range(3)]
assert results == [False, False, True], results
guard.reset()
polling = [guard.repeated("processOutput", '{"pid":1}') for _ in range(5)]
assert polling == [False] * 5, polling
print("repeat guard ok")

# ---------- 5. 报告结构 ----------
report_data = report(mem.records(), window=128000, budgets={})
assert {"session", "turn", "last", "window"} <= set(report_data)
print("report shape ok")

print("\nUSAGE TEST OK")
