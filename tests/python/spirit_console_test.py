"""控制台输入测试：单 reader 路由、审批配对、超时 / 取消 / EOF、CLI 接线。"""
import json
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from UserInput.Console import Console  # noqa: E402


def wait_until(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def make():
    lines = queue.Queue()
    console = Console()
    console.start(reader=lambda: lines.get())
    return console, lines


def shutdown(console, lines):
    console.close()
    lines.put(None)   # 叫醒注入的 reader（真实 input() 靠进程退出）


def ask_in_thread(console, request=None, timeout=3.0):
    result = {}

    def run():
        result["value"] = console.ask(
            request or {"name": "test_cap", "call_id": "c1", "arguments": "{}"},
            timeout=timeout,
        )

    thread = threading.Thread(target=run)
    thread.start()
    assert wait_until(lambda: console.asking), "ask 没有进入 pending"
    return thread, result


# ---------- 1. 用户消息走队列 ----------
console, lines = make()
lines.put("hello")
assert console.read("") == "hello"
lines.put("world")
assert console.read("") == "world"
shutdown(console, lines)
print("user messages ok")

# ---------- 2. 先到的消息不会被审批吃掉 ----------
console, lines = make()
lines.put("先到的消息")
assert wait_until(lambda: console.queued() == 1), console.queued()
thread, result = ask_in_thread(console)
lines.put("y")
thread.join(3)
assert result["value"][0] is True, result
assert console.read("") == "先到的消息"
shutdown(console, lines)
print("stale message kept ok")

# ---------- 3. pending 期间的行是审批答案，不进消息队列 ----------
console, lines = make()
thread, result = ask_in_thread(console)
lines.put("这是一条普通文本")
thread.join(3)
assert result["value"][0] is False, result
assert "用户拒绝" in result["value"][1], result
assert console.queued() == 0, console.queued()
shutdown(console, lines)
print("pending routing ok")

# ---------- 4. 超时后的回答变回用户消息 ----------
console, lines = make()
thread, result = ask_in_thread(console, timeout=0.3)
thread.join(3)
assert result["value"][0] is False, result
assert "超时" in result["value"][1], result
assert wait_until(lambda: not console.asking)
lines.put("y")
assert console.read("") == "y"
shutdown(console, lines)
print("timeout residue ok")

# ---------- 5. cancel_pending 叫醒审批 ----------
console, lines = make()
thread, result = ask_in_thread(console)
console.cancel_pending("用户停止")
thread.join(3)
assert result["value"] == (False, "用户停止"), result
shutdown(console, lines)
print("cancel pending ok")

# ---------- 6. EOF：pending 拒绝 + read 抛 EOFError ----------
console, lines = make()
thread, result = ask_in_thread(console)
lines.put(None)
thread.join(3)
assert result["value"][0] is False and "输入结束" in result["value"][1], result
try:
    console.read("")
    raise AssertionError("EOF 后 read 没有抛错")
except EOFError:
    pass
shutdown(console, lines)
print("eof ok")

# ---------- 7. 关闭时挂起的审批按拒绝收 ----------
console, lines = make()
thread, result = ask_in_thread(console)
console.close()
thread.join(3)
assert result["value"][0] is False and "关闭" in result["value"][1], result
try:
    console.read("")
    raise AssertionError("关闭后 read 没有抛错")
except EOFError:
    pass
lines.put(None)
print("close ok")

# ---------- 8. Ctrl+C 作废下一行 ----------
console, lines = make()
console.discard_next(5.0)
lines.put("被作废的半行")
lines.put("真正的消息")
assert wait_until(lambda: console.queued() >= 1), console.queued()
assert console.read("") == "真正的消息"
shutdown(console, lines)
print("discard next ok")

# ---------- 9. 重入审批直接抛错 ----------
console, lines = make()
thread, result = ask_in_thread(console)
try:
    console.ask({"name": "second", "call_id": "c2"}, timeout=0.2)
    raise AssertionError("重入没有抛错")
except RuntimeError:
    pass
console.cancel_pending("用户停止")
thread.join(3)
shutdown(console, lines)
print("reentry guard ok")

# ---------- 10. 交替 100 行不串台 ----------
console, lines = make()
for index in range(100):
    lines.put(f"m{index}")
    assert console.read("") == f"m{index}"
thread, result = ask_in_thread(console)
lines.put("y")
thread.join(3)
assert result["value"][0] is True
lines.put("m-final")
assert console.read("") == "m-final"
shutdown(console, lines)
print("alternating 100 ok")

# ---------- 11. Ctrl+C 状态机 ----------
import MoBo.main as mobo  # noqa: E402


class FakeEngine:
    def __init__(self, target):
        self.target = target
        self.interrupts = 0
        self.stops = 0

    def interrupt(self):
        self.interrupts += 1
        self.target.cancel_pending("用户停止")

    def stop(self):
        self.stops += 1
        self.target.close()


original_console = mobo.console
try:
    # 11a. 审批挂起：一次取消审批 + 中断；两秒内第二次退出
    local = Console()
    lines = queue.Queue()
    local.start(reader=lambda: lines.get())
    mobo.console = local
    fake = FakeEngine(local)
    handler = mobo._sigint_handler(fake, {"at": 0.0})
    thread, result = ask_in_thread(local)
    handler(None, None)
    thread.join(3)
    assert result["value"][0] is False, result
    assert "用户停止" in result["value"][1], result
    assert fake.interrupts == 1 and fake.stops == 0, (fake.interrupts, fake.stops)
    handler(None, None)
    assert fake.stops == 1, fake.stops
    lines.put(None)

    # 11b. 空闲等输入：一次 Ctrl+C 作废下一行，reader 继续工作
    local = Console()
    lines = queue.Queue()
    local.start(reader=lambda: lines.get())
    mobo.console = local
    fake = FakeEngine(local)
    handler = mobo._sigint_handler(fake, {"at": 0.0})
    got = {}
    reader_thread = threading.Thread(target=lambda: got.setdefault("v", local.read("")))
    reader_thread.start()
    assert wait_until(lambda: local.reading)
    handler(None, None)
    assert fake.interrupts == 0, fake.interrupts
    lines.put("被作废的半行")
    lines.put("真正的消息")
    reader_thread.join(3)
    assert got.get("v") == "真正的消息", got
    lines.put(None)

    # 11c. 流式 / 工具中：既不在审批也不在读输入 -> 中断本轮
    local = Console()
    lines = queue.Queue()
    local.start(reader=lambda: lines.get())
    mobo.console = local
    fake = FakeEngine(local)
    handler = mobo._sigint_handler(fake, {"at": 0.0})
    handler(None, None)
    assert fake.interrupts == 1 and fake.stops == 0, (fake.interrupts, fake.stops)
    lines.put(None)
finally:
    mobo.console = original_console
print("sigint state machine ok")

# ---------- 12. CLI 接线：消息 → 模型 → 审批 → 工具 → 退出 ----------
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from Provider import adapter  # noqa: E402
import MoBo.main as mobo  # noqa: E402
from UserInput.Console import console as cli_console  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-console-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-console-work-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("rules")
config.set("engine.untrusted_policy", "warn")

cli_lines = queue.Queue()
cli_console.start(reader=lambda: cli_lines.get())
engine.set_input_source(lambda: cli_console.read(""))
engine.set_approver(mobo._console_approver, cli_console.cancel_pending)

calls = {"n": 0}


def fake_model(handle, bundle, schemas, thinking_on, effort="medium"):
    calls["n"] += 1
    if calls["n"] == 1:
        item = NS(
            type="function_call",
            call_id="write-1",
            name="writeFile",
            arguments=json.dumps({"path": "approved.txt", "content": "ok"}),
        )
        return iter([NS(type="response.completed", response=NS(output=[item]))])
    return iter([NS(type="response.completed", response=NS(output=[]))])


original_create = adapter.create
adapter.create = fake_model
try:
    assert engine.start()
    runner = threading.Thread(target=engine.run)
    runner.start()

    cli_lines.put("写文件")
    assert wait_until(lambda: cli_console.asking, 10), "CLI approver 没有被调用"
    cli_lines.put("y")
    assert wait_until(lambda: (work / "approved.txt").exists(), 10), "审批后文件没写出来"
    assert (work / "approved.txt").read_text(encoding="utf-8") == "ok"

    cli_lines.put("exit")
    runner.join(timeout=10)
    assert not runner.is_alive(), "exit 没有让引擎停下"
finally:
    adapter.create = original_create
    cli_console.close()
    cli_lines.put(None)
print("cli wiring ok:", calls["n"], "model calls")

print("\nCONSOLE TEST OK")
