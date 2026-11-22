"""可中断等待：审批取消 / 摘要取消 / stream epoch。"""
import json
import os
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Cancel import token as cancel_token  # noqa: E402
from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU import Summary as summary_module  # noqa: E402
from Memory import STREAM, mem  # noqa: E402
from Memory.ModO import modo  # noqa: E402
from Provider import adapter  # noqa: E402


# ---------- 1. Engine.interrupt() 取消挂起审批 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-interrupt-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-interrupt-work-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("rules")
config.set("engine.untrusted_policy", "warn")

approver_called = threading.Event()
answers = queue.Queue()


def approver(request):
    approver_called.set()
    return answers.get(timeout=10)


def cancel_approver():
    answers.put(False)


engine.set_approver(approver, cancel_approver)
calls = {"n": 0}


def fake_model(handle, bundle, schemas, thinking_on, effort="medium"):
    calls["n"] += 1
    item = NS(type="function_call", call_id="write-1", name="writeFile",
              arguments=json.dumps({"path": "never.txt", "content": "x"}))
    return iter([NS(type="response.completed", response=NS(output=[item]))])


original = adapter.create
adapter.create = fake_model
seen = []


def source():
    if seen:
        raise EOFError
    seen.append(1)
    return "写文件"


try:
    engine.set_input_source(source)
    assert engine.start()
    runner = threading.Thread(target=engine.run)
    runner.start()
    assert approver_called.wait(5), "approver not called"
    started = time.time()
    engine.interrupt()
    runner.join(timeout=5)
    elapsed = time.time() - started
    assert not runner.is_alive(), "engine did not stop after interrupt"
    assert elapsed < 2, elapsed
    assert not (work / "never.txt").exists()
    print("approval cancel ok:", round(elapsed, 2), "s")
finally:
    adapter.create = original
    security.set_approver(None, None)

# ---------- 2. Summary 被取消 ----------
original_request = summary_module.modi.request


def slow_stream(bundle):
    while True:
        yield NS(type="response.output_text.delta", delta="x")
        time.sleep(0.1)


summary_module.modi.request = slow_stream
cancel_token.clear()
result = {}


def run_summary():
    result["text"] = summary_module.summary.summarize(
        [{"role": "user", "content": "很长的一段话"}]
    )


thread = threading.Thread(target=run_summary)
thread.start()
time.sleep(0.3)
cancel_token.set()
thread.join(timeout=3)
summary_module.modi.request = original_request
assert not thread.is_alive(), "summary did not cancel"
assert result["text"] == "", result
print("summary cancel ok")
cancel_token.clear()

# ---------- 3. stream 片段带 epoch ----------
mem.clear_transient(STREAM)
stream = [
    NS(type="response.output_text.delta", delta="hello"),
    NS(type="response.completed", response=NS(output=[])),
]
modo.consume(iter(stream), epoch=7)
items = list(mem.transient(STREAM))
assert items and any(isinstance(item, dict) and item.get("epoch") == 7 for item in items), items
print("stream epoch ok:", items)

print("\nINTERRUPT TEST OK")
