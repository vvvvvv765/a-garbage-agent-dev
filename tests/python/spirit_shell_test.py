"""持久 shell 测试：cd/export 保留、并发串行、取消重开、换工作区、exit。"""
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-shell-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-shell-work-"))
work2 = Path(tempfile.mkdtemp(prefix="spirit-shell-work2-"))
(work / "sub").mkdir()
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")


def call(command, call_id="c"):
    raw = json.dumps({"bashinput": command})
    out = capabilities.run([
        CapabilityInput(call_id, "bash", raw, {"bashinput": command})
    ])[0]
    assert out.ok, out.content
    return out.content


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


# ---------- 状态保留 ----------
assert work.name in call("pwd")
call("cd sub")
assert "sub" in call("pwd")
call("export SPIRIT_STATE=hello")
assert "hello" in call('echo "$SPIRIT_STATE"')
print("cd / export persist ok")

# ---------- 并发串行 ----------
def one(i):
    return call(f"echo concurrent-{i}", f"c{i}")

with ThreadPoolExecutor(max_workers=4) as pool:
    outputs = list(pool.map(one, range(8)))
assert all(f"concurrent-{i}" in outputs[i] for i in range(8)), outputs
print("concurrent bash serialized ok")

# ---------- 取消后重开 ----------
holder = {}


def long_call():
    holder["out"] = capabilities.run([
        CapabilityInput("c-sleep", "bash",
                        '{"bashinput":"sleep 20"}', {"bashinput": "sleep 20"})
    ])[0]


thread = threading.Thread(target=long_call)
thread.start()
assert wait_until(lambda: len(capabilities.running()) > 0, 5)
capabilities.cancel_all("测试取消")
thread.join(timeout=5)
assert not thread.is_alive()
assert not holder["out"].ok and "已取消" in holder["out"].content, holder["out"].content
assert work.name in call("pwd")
print("cancel + restart ok")

# ---------- 换工作区：旧 shell 停掉 ----------
call("cd sub")
engine.select_workspace(work2)
out = call("pwd")
assert work2.name in out, out
assert "sub" not in out
print("workspace change restarts shell ok")

# ---------- exit 后重开 ----------
out = call("exit")
assert "shell 已退出" in out, out
assert work2.name in call("pwd")
print("exit + restart ok")

print("\nSHELL TEST OK")
