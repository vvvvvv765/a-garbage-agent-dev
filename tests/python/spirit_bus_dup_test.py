"""信息表登记规则测试：报告可覆盖、句柄不许被静默顶掉。"""
import sys

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Bus.NeutralTable import NeutralTable  # noqa: E402
from Contract import Contract  # noqa: E402

table = NeutralTable()

# ---------- 1. Contract（报告 / 控制）：按设计反复覆盖 ----------
table.register("signal", Contract(SI=True))
table.register("signal", Contract(SI=False))
assert table.get("signal").SI is False
print("contract overwrite ok")

# ---------- 2. 句柄：同一个对象重复登记没事 ----------
class Handle:
    pass


handle = Handle()
table.register("port", handle)
table.register("port", handle)
assert table.get("port") is handle
print("same handle re-register ok")

# ---------- 3. 句柄：换个对象直接顶掉 = 启动顺序出事，报错 ----------
try:
    table.register("port", Handle())
    raise AssertionError("不同句柄覆盖同一个 key 应该报错")
except RuntimeError as error:
    assert "重复登记" in str(error), error
print("duplicate handle blocked ok")

# ---------- 4. 确实要换：显式 replace=True ----------
replacement = Handle()
table.register("port", replacement, replace=True)
assert table.get("port") is replacement
print("explicit replace ok")

# ---------- 5. 全局表：重复开机不炸（CPU 复用渲染队列 / BIOS 换句柄） ----------
import os  # noqa: E402
import tempfile  # noqa: E402

os.environ["SPIRIT_HOME"] = tempfile.mkdtemp(prefix="spirit-bus-home-")
from Bus import NT, keys  # noqa: E402
from Contract import InstructionQueue  # noqa: E402
from DC.CPU import CPU  # noqa: E402

NT.register(keys.AGENT_START, Contract(SI=True))
first = CPU()
first.attach(gpu=object(), memory=object(), input_source=object())
first.boot()
queue = NT.get(keys.CPU_RENDER)
assert isinstance(queue, InstructionQueue)

second = CPU()
second.attach(gpu=object(), memory=object(), input_source=object())
second.boot()   # 再开机：复用原队列，不应该报重复登记
assert NT.get(keys.CPU_RENDER) is queue
print("reboot reuse ok")

print("ALL BUS DUP TESTS PASSED")
