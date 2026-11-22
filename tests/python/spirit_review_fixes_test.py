"""外部审查第一批修复：命令闸绕过 / 替换文件安全 / 失败流 / 熔断并发。"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-review-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC.Failover import failover  # noqa: E402
from Engine import Engine  # noqa: E402
from Paths import config_file  # noqa: E402
from Provider.Adapter import ProviderStreamError, _ResponsesStream  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-review-home-"))
work = home / "workspace"
work.mkdir(parents=True, exist_ok=True)
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")
assert engine.start()


def precheck(command):
    return capabilities.precheck("bash", {"command": command})


# ---------- 1. echo 命令替换不能靠豁免绕过 ----------
ok, reason = precheck('echo $(rm -rf "$HOME/..")')
assert ok is False and "灾难闸" in reason, (ok, reason)
print("1. echo 替换绕过已堵 ok")

# ---------- 2. powershell -e / -enc 编码执行 ----------
for command in (
    "powershell -e " + "QQBBAEE=" * 4,
    "powershell -enc " + "QQBBAEE=" * 4,
    "powershell -EncodedCommand " + "QQBBAEE=" * 4,
):
    ok, reason = precheck(command)
    assert ok is False and "灾难闸" in reason, (command, ok, reason)
print("2. 编码执行已堵 ok")

# ---------- 3. Git Bash /c/... 也命中机器数据保护 ----------
cfg = Path(config_file()).resolve()
text = str(cfg).replace("\\", "/")
msys = "/" + text[0].lower() + text[2:]
ok, reason = precheck(f"cat {msys}")
assert ok is False and "沙箱拒绝" in reason, (msys, ok, reason)
print("3. /c/ 路径保护 ok")

# ---------- 4. replaceInFile：负数 / 大文件 / 换行 ----------
from Capabilities import CapabilityInput  # noqa: E402

target = work / "note.txt"
target.write_bytes(b"alpha\nbeta\n")
raw = json.dumps({"path": str(target), "old_text": "alpha", "new_text": "ALPHA", "occurrence": -1})
out = capabilities.run([CapabilityInput("c-neg", "replaceInFile", raw, json.loads(raw))])[0]
assert "负数" in out.content, out.content
assert target.read_bytes() == b"alpha\nbeta\n", "负数 occurrence 不能改文件"

raw = json.dumps({"path": str(target), "old_text": "alpha", "new_text": "ALPHA"})
out = capabilities.run([CapabilityInput("c-ok", "replaceInFile", raw, json.loads(raw))])[0]
assert out.ok, out.content
assert target.read_bytes() == b"ALPHA\nbeta\n", target.read_bytes()
assert b"\r\n" not in target.read_bytes(), "不能把 LF 静默改成 CRLF"

big = work / "big.txt"
big.write_bytes(b"x" * (2 * 1024 * 1024 + 10))
raw = json.dumps({"path": str(big), "old_text": "x", "new_text": "y"})
out = capabilities.run([CapabilityInput("c-big", "replaceInFile", raw, json.loads(raw))])[0]
assert "太大" in out.content, out.content
print("4. replaceInFile 三个 bug 已修 ok")

# ---------- 5. response.failed 不再伪装成功 ----------
class Event:
    def __init__(self, kind, item=None, response=None):
        self.type = kind
        self.item = item
        self.response = response


class Chunk:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


failed = Event("response.failed", response=Chunk(error="boom"))
try:
    list(_ResponsesStream(iter([failed])))
    raise AssertionError("response.failed 应该抛错")
except ProviderStreamError:
    pass
print("5. 失败流不再伪装成功 ok")

# ---------- 6. ReDoS 有超时，不占死线程 ----------
evil = work / "evil.txt"
evil.write_text("a" * 50000 + "!", encoding="utf-8")
raw = json.dumps({"pattern": "(a+)+$", "path": str(work), "glob": "evil.txt"})
started = time.time()
out = capabilities.run([CapabilityInput("c-redos", "searchFiles", raw, json.loads(raw))])[0]
elapsed = time.time() - started
assert "超时" in out.content and elapsed < 5, (out.content, elapsed)
print("6. ReDoS 超时 ok:", round(elapsed, 2), "s")

# ---------- 7. SSRF 地址校验 ----------
from Capabilities.FetchUrl import _allowed  # noqa: E402

for url in ("http://127.0.0.1/", "http://169.254.169.254/", "http://2130706433/",
            "http://0x7f000001/", "http://[::1]/"):
    assert _allowed(url)[0] is False, url
assert _allowed("http://8.8.8.8/")[0] is True
print("7. SSRF 校验 ok")

# ---------- 8. 熔断状态并发读写不炸 ----------
errors = []


def writer():
    for index in range(2000):
        failover.record("p1", index % 2 == 0)


def reader():
    try:
        for _ in range(2000):
            failover.snapshot()
    except Exception as error:   # noqa: BLE001
        errors.append(error)


threads = [threading.Thread(target=writer) for _ in range(3)]
threads += [threading.Thread(target=reader) for _ in range(3)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
assert not errors, errors
failover.reset()
print("8. 熔断并发 ok")

# ---------- 9. 会话锁：轮次在跑时切换会话被拒 ----------
from Bus import NT, keys  # noqa: E402

lock = NT.get(keys.SESSION_LOCK)
assert lock is not None
holder = threading.Event()
release = threading.Event()


def hold_lock():
    lock.acquire()
    holder.set()
    release.wait(5)
    lock.release()


lock_thread = threading.Thread(target=hold_lock)
lock_thread.start()
assert holder.wait(2)
try:
    engine.new_session()
    raise AssertionError("锁被占用时 new_session 应该拒绝")
except RuntimeError:
    pass
finally:
    release.set()
    lock_thread.join(2)
print("9. 会话锁 ok")

# ---------- 10. 执行池超时后自动换池（S1 缓解） ----------
class HangCap:
    name = "hang_cap"
    description = "挂住"
    parameters = {"type": "object", "properties": {}}

    def spec(self):
        from Capabilities import CapabilitySpec
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="read", timeout=0.4)

    def run(self, arguments):
        time.sleep(2)
        return "late"


class FastCap:
    name = "fast_cap"
    description = "快"
    parameters = {"type": "object", "properties": {}}

    def spec(self):
        from Capabilities import CapabilitySpec
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="read")

    def run(self, arguments):
        return "fast-ok"


from Capabilities import CapabilityInput  # noqa: E402

engine.register_capability(HangCap())
engine.register_capability(FastCap())
outputs = capabilities.run([
    CapabilityInput(f"h{i}", "hang_cap", "{}", {}) for i in range(4)
])
assert all(not item.ok and "超时" in item.content for item in outputs), [
    item.content for item in outputs
]
out = capabilities.run([CapabilityInput("f1", "fast_cap", "{}", {})])[0]
assert out.ok and "fast-ok" in out.content, out.content
print("10. 执行池换池 ok")

print("\nALL REVIEW FIX TESTS PASSED")
