"""side_effect 测试：声明、批内串行、Security 只读来源。"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Cancel import token as cancel_token  # noqa: E402
from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-effect-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-effect-work-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("rules")
cancel_token.clear()

# ---------- 1. 内置声明 ----------
assert capabilities.side_effect("readFile") == "read"
assert capabilities.side_effect("fetchUrl") == "external"
assert capabilities.side_effect("webSearch") == "external"
assert capabilities.side_effect("bash") == "write"
assert capabilities.side_effect("processOutput") == "read"
assert capabilities.side_effect("todoRead") == "read"
assert capabilities.side_effect("does_not_exist") == "write"
print("side_effect declarations ok")

# ---------- 2. 批内调度 ----------
starts = {}


class Probe:
    def __init__(self, name, effect):
        self.name = name
        self.effect = effect

    def spec(self):
        return CapabilitySpec(
            self.name, "probe", {"type": "object", "properties": {}},
            side_effect=self.effect,
        )

    def run(self, arguments):
        starts.setdefault(self.name, []).append(time.time())
        time.sleep(0.3)
        return self.name


capabilities.register(Probe("read_a", "read"))
capabilities.register(Probe("read_b", "read"))
capabilities.register(Probe("write_a", "write"))


def call_batch(names):
    inputs = [CapabilityInput(f"c-{i}", name, "{}", {}) for i, name in enumerate(names)]
    started = time.time()
    outputs = capabilities.run(inputs)
    return outputs, time.time() - started


# 读-读：并行（约 0.3s）
outputs, elapsed = call_batch(["read_a", "read_b"])
assert all(item.ok for item in outputs), outputs
assert elapsed < 0.55, elapsed
print("read/read parallel ok:", round(elapsed, 2), "s")

# 读里有写：整批串行（约 0.6s）
outputs, elapsed = call_batch(["read_a", "write_a"])
assert all(item.ok for item in outputs), outputs
assert elapsed >= 0.55, elapsed
assert starts["read_a"][-1] <= starts["write_a"][-1]
print("read/write serial ok:", round(elapsed, 2), "s")

# 取消后串行批不再执行
cancel_token.set()
outputs, elapsed = call_batch(["read_a", "write_a"])
assert all(not item.ok and "已取消" in item.content for item in outputs), outputs
assert elapsed < 0.3, elapsed
cancel_token.clear()
print("serial batch cancel ok")

for name in ("read_a", "read_b", "write_a"):
    capabilities.unregister(name)

# ---------- 3. Security 只读来自 spec ----------
# rules + 无审批：只读放行，写拒绝
security.set_approver(None, None)
allowed, reason = security.check("processOutput", '{"id":"p1"}')
assert allowed and reason == "readonly", (allowed, reason)
allowed, reason = security.check("bash", '{"bashinput":"echo x"}')
assert not allowed and "没有接入审批" in reason, (allowed, reason)

requests = []
security.set_approver(lambda request: requests.append(dict(request)) or True)
allowed, _ = security.check("readFile", '{"path":"x"}')
assert allowed and not requests
allowed, _ = security.check("writeFile", '{"path":"x"}')
assert allowed and requests and requests[-1]["name"] == "writeFile"
print("security readonly from spec ok")

print("\nSIDE EFFECT TEST OK")
