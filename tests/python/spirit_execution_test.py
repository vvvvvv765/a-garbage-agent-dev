"""执行子体系测试：取消 / 超时 / 杀进程 / CPU 停止。"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-exec-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import TOOL_OUTPUT, mem  # noqa: E402
from Provider import adapter  # noqa: E402


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


# ---------- 1. 直接跑一个长 bash，取消 ----------
holder = {}


def run_long():
    start = time.time()
    holder["out"] = capabilities.run([
        CapabilityInput(
            "c-cancel", "bash",
            '{"bashinput":"sleep 20"}', {"bashinput": "sleep 20"},
        )
    ])[0]
    holder["elapsed"] = time.time() - start


thread = threading.Thread(target=run_long)
thread.start()
assert wait_until(lambda: len(capabilities.running()) > 0), "execution not registered"
print("running:", capabilities.running())
time.sleep(0.6)
count = capabilities.cancel_all("测试取消")
print("cancelled:", count)
thread.join(timeout=5)
assert not thread.is_alive(), "cancel did not unblock within 5s"
assert holder["elapsed"] < 3, holder["elapsed"]
assert not holder["out"].ok and "已取消" in holder["out"].content, holder["out"].content
assert capabilities.running() == [], capabilities.running()
print("bash cancel ok, elapsed:", round(holder["elapsed"], 2))

# ---------- 2. 超时仍然有效（慢能力不能拖满） ----------
class SlowCap:
    def spec(self):
        return CapabilitySpec(
            name="slow_cancel_cap", description="睡很久", parameters={"type": "object"},
            timeout=0.5,
        )

    def run(self, arguments):
        time.sleep(4)
        return "终于好了"


capabilities.register(SlowCap())
start = time.time()
out = capabilities.run([
    CapabilityInput("c-slow", "slow_cancel_cap", "{}", {})
])[0]
elapsed = time.time() - start
assert not out.ok and "超时" in out.content, out.content
assert elapsed < 1.5, elapsed
print("timeout still fast ok:", round(elapsed, 2))

# ---------- 3. CPU 停止按钮：模型流 + 工具一起停 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-exec-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-exec-work-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")

calls = {"n": 0}


def fake_model(handle, bundle, schemas, thinking_on, effort="medium"):
    calls["n"] += 1
    item = NS(
        type="function_call", call_id="call_long",
        name="bash", arguments=json.dumps({"bashinput": "sleep 20"}),
    )
    return iter([NS(type="response.completed", response=NS(output=[item]))])


original = adapter.create
adapter.create = fake_model
seen = []


def source():
    if seen:
        raise EOFError
    seen.append(1)
    return "跑个长命令"


engine.set_input_source(source)
assert engine.start()
mark = len(mem.records())
runner = threading.Thread(target=engine.run)
runner.start()

try:
    assert wait_until(lambda: len(engine.running()) > 0, 8), "engine tool not running"
    print("engine running:", engine.running())
    start = time.time()
    engine.interrupt()
    runner.join(timeout=8)
    stop_elapsed = time.time() - start
    assert not runner.is_alive(), "engine did not stop after interrupt"
    assert stop_elapsed < 5, stop_elapsed
    mem.flush()
    outputs = [
        record.payload.get("output", "")
        for record in mem.records_after(mark)
        if record.address == TOOL_OUTPUT
    ]
    assert outputs and any("已取消" in str(text) for text in outputs), outputs
    assert calls["n"] == 1, calls  # 停止后不再请求模型
    print("engine interrupt ok, elapsed:", round(stop_elapsed, 2), "| output:", outputs[0][:40])
finally:
    adapter.create = original

print("\nEXECUTION TEST OK")
