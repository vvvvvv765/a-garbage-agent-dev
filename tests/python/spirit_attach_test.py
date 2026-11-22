"""装配注入测试：CPU 不 import 主体系，只拿句柄；缺装配不开机；一轮走假件。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Bus import NT, keys  # noqa: E402
from Contract import Contract  # noqa: E402
from DC.CPU import CPU  # noqa: E402

# ---------- 1. 静态：CPU 不再 import 主体系的具体单例 ----------
source = Path(root, "DC", "CPU.py").read_text(encoding="utf-8")
for forbidden in (
    "from GPU import",
    "from UserInput import",
    "from Memory.ModO import",
    "from Memory.Persist import",
):
    assert forbidden not in source, f"CPU 仍然直接 import：{forbidden}"
assert "def attach(" in source
print("static imports ok")

# ---------- 2. 没装配就不开机 ----------
bare = CPU()
NT.register(keys.AGENT_START, Contract(SI=True))
bare.boot()
assert bare.start is False, "缺装配时不应开机"
assert bare.attached() == {"gpu": False, "memory": False, "input": False, "failover": False}
print("missing attachment blocks boot ok")

# ---------- 3. 装配假件：一轮走注入的句柄 ----------
class FakeGPU:
    def __init__(self):
        self.calls = 0

    def request(self):
        self.calls += 1
        return None


class FakeMemory:
    def __init__(self):
        self.saved = 0
        self.stopped = 0
        self.consumed = 0

    def records(self):
        return []

    def records_after(self, mark):
        return []

    def flush(self):
        pass

    def consume(self, stream, should_stop=None, epoch=0):
        self.consumed += 1
        return []

    def save(self, path=None):
        self.saved += 1

    def stop(self):
        self.stopped += 1


class FakeInput:
    def __init__(self):
        self.reads = 0

    def uim(self):
        self.reads += 1
        # 读一次就发关机报告：这一轮跑完 CPU 自己退出
        NT.register(keys.USER_INPUT, Contract(start=False, SI=True, skip=False))


fake_gpu = FakeGPU()
fake_memory = FakeMemory()
fake_input = FakeInput()

cpu = CPU()
cpu.attach(gpu=fake_gpu, memory=fake_memory, input_source=fake_input)
assert cpu.attached() == {"gpu": True, "memory": True, "input": True, "failover": False}
cpu.boot()
assert cpu.start is True, "装配齐全应能开机"
cpu.run()

assert fake_input.reads == 1, fake_input.reads
assert fake_memory.saved >= 1, fake_memory.saved
assert fake_memory.stopped == 1, fake_memory.stopped
assert fake_gpu.calls == 0, "关机轮不该请求模型"
print("injected turn ok:", {"input": fake_input.reads, "save": fake_memory.saved})

# ---------- 4. 真实装配：Engine 构造后 CPU 三个句柄齐全 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-attach-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-attach-work-"))
from Engine import Engine  # noqa: E402
from DC import DC  # noqa: E402

Engine(home=home, workdir=work)
assert DC.attached() == {"gpu": True, "memory": True, "input": True, "failover": True}, DC.attached()
print("engine assembly ok")

print("ALL ATTACH TESTS PASSED")
