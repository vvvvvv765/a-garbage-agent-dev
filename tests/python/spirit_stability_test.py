"""稳定性：单实例锁 + 能力队列上限/背压。"""
import os
import sys
import tempfile
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR",
             "SPIRIT_ALLOW_MULTI"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, CapabilityOutput, CapabilitySpec, capabilities  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from MoBo.lock import InstanceLock  # noqa: E402

# ---------- 1. 单实例锁：同一个数据根第二个进程拿不到 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-lock-"))
first = InstanceLock(home).acquire()
try:
    try:
        InstanceLock(home).acquire()
        raise AssertionError("同一个数据根不该能拿第二次")
    except RuntimeError as error:
        assert "另一个" in str(error), error
finally:
    first.release()
# 释放后可以再拿
second = InstanceLock(home).acquire()
second.release()
# 不同数据根互不影响
other = InstanceLock(Path(tempfile.mkdtemp(prefix="spirit-lock2-"))).acquire()
other.release()
print("1. 单实例锁 ok")

# ---------- 2. 能力队列上限：满了直接拒绝回模型 ----------
work = Path(tempfile.mkdtemp(prefix="spirit-queue-work-"))
engine = Engine(home=home, workdir=work)
config.set("engine.capability_queue", 1)


class SlowCapability:
    name = "slow_cap"
    description = "测试用：慢能力"
    parameters = {"type": "object", "properties": {}, "required": []}

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters, side_effect="read")

    def run(self, arguments):
        time.sleep(0.6)
        return "slow-ok"


engine.register_capability(SlowCapability())
outputs = capabilities.run([
    CapabilityInput("q1", "slow_cap", "{}", {}),
    CapabilityInput("q2", "slow_cap", "{}", {}),
])
assert len(outputs) == 2, outputs
ok = [out for out in outputs if out.ok]
rejected = [out for out in outputs if not out.ok]
assert len(ok) == 1 and len(rejected) == 1, [(o.ok, o.content) for o in outputs]
assert "队列已满" in rejected[0].content, rejected[0].content
print("2. 能力队列上限 ok")

# ---------- 2b. 入口锁要留住引用（否则文件句柄一回收，锁就没了） ----------
env_home = Path(tempfile.mkdtemp(prefix="spirit-entry-lock-"))
from Paths import home as paths_home, set_home  # noqa: E402
prev_root = paths_home()
set_home(None)                       # 之前 Engine(home=...) 注入过根，这里按环境变量走
os.environ["SPIRIT_HOME"] = str(env_home)
from MoBo import lock as lock_mod  # noqa: E402
held = lock_mod.acquire_for_current_home()
assert held is not None
try:
    InstanceLock(env_home).acquire()
    raise AssertionError("入口锁持有期间，同数据根不该再拿得到")
except RuntimeError:
    pass
lock_mod._HELD.release()
lock_mod._HELD = None
os.environ.pop("SPIRIT_HOME", None)
set_home(prev_root)
print("2b. 入口锁生命周期 ok")

# 队列恢复后还能继续用
time.sleep(0.2)
again = capabilities.run([CapabilityInput("q3", "slow_cap", "{}", {})])
assert again[0].ok, again[0].content
print("3. 队列释放后恢复 ok")

print("ALL STABILITY TESTS PASSED")
