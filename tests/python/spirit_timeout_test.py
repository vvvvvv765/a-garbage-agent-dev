"""能力超时 + 每能力异常 handler 测试。"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-timeout-")

from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402
from Memory import EXCEPTION, mem  # noqa: E402


class SlowCap:
    def spec(self):
        return CapabilitySpec(
            name="slow_cap", description="睡很久", parameters={"type": "object"},
            timeout=0.5,
        )

    def run(self, arguments):
        time.sleep(3)
        return "终于好了"


class BoomCap:
    def spec(self):
        return CapabilitySpec(
            name="boom_cap", description="直接炸", parameters={"type": "object"},
            timeout=5,
        )

    def run(self, arguments):
        raise RuntimeError("故意失败")


capabilities.register(SlowCap())
capabilities.register(BoomCap())


def call(name):
    return capabilities.run([CapabilityInput(f"c-{name}", name, "{}", {})])[0]


# 1. 超时
start = time.time()
out = call("slow_cap")
elapsed = time.time() - start
assert not out.ok and "超时" in out.content, out
assert elapsed < 2, elapsed
print("timeout ok:", out.content, f"({elapsed:.2f}s)")

# 2. 异常
out = call("boom_cap")
assert not out.ok and "故意失败" in out.content, out
print("exception ok:", out.content)

# 3. 异常记录点名到具体能力
mem.flush()
records = [r.payload for r in mem.records() if r.address == EXCEPTION]
systems = [r.get("system") for r in records]
print("fault systems:", systems)
assert "capability:slow_cap" in systems, systems
assert "capability:boom_cap" in systems, systems

# 4. 超时之后池子还能用
out = capabilities.run([CapabilityInput("c-bash", "bash", '{"bashinput":"echo alive"}', {"bashinput": "echo alive"})])[0]
assert out.ok and "alive" in out.content, out
print("pool alive:", out.content.strip())

print("TIMEOUT TEST OK")
