"""引擎压力测试：并发内存 / 能力池 / 大文件 / 会话 / 进程 / SSE / 假模型全链路。"""
import json
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
SESSION_DIR = tempfile.mkdtemp(prefix="spirit-stress-")
os.environ["SPIRIT_SESSION_DIR"] = SESSION_DIR
os.environ["SPIRIT_HOME"] = tempfile.mkdtemp(prefix="spirit-stress-home-")

from Capabilities import CapabilityInput, capabilities           # noqa: E402
from Config import config                                       # noqa: E402
from Engine import Engine                                       # noqa: E402
from Memory import mem, TOOL_CALL, TOOL_OUTPUT                  # noqa: E402
from Memory.Persist import persist                              # noqa: E402
from Provider import adapter                                    # noqa: E402
from WebUI import Output                                        # noqa: E402

ok = []


def section(name):
    print(f"\n=== {name} ===")


# ---------- 1. 内存并发 ----------
section("memory concurrency")
mem.clear()
threads = []
for t in range(8):
    def worker(t=t):
        for i in range(500):
            mem.submit("user", f"{t}-{i}")
    th = threading.Thread(target=worker)
    threads.append(th)
    th.start()
for th in threads:
    th.join()
mem.flush()
records = mem.records()
assert len(records) == 4000, len(records)
assert [r.seq for r in records] == list(range(1, 4001)), "seq 不连续"
ok.append("memory 8x500")
print("records:", len(records))

# ---------- 2. 能力池并发 + 超时 ----------
section("capability pool")


class Slow:
    def spec(self):
        from Capabilities import CapabilitySpec
        return CapabilitySpec("slow_x", "慢", {"type": "object"}, timeout=0.3)

    def run(self, arguments):
        time.sleep(2)
        return "late"


capabilities.register(Slow())
inputs = [
    CapabilityInput(f"c{i}", "bash", '{"bashinput":"echo ok"}', {"bashinput": "echo ok"})
    for i in range(30)
]
outputs = capabilities.run(inputs)
assert len(outputs) == 30 and all(o.ok and "ok" in o.content for o in outputs)
start = time.time()
slow = capabilities.run([CapabilityInput("s1", "slow_x", "{}", {})])[0]
elapsed = time.time() - start
assert not slow.ok and "超时" in slow.content and elapsed < 1.5, (slow, elapsed)
print("30 batch + timeout ok", f"{elapsed:.2f}s")
ok.append("pool 30 + timeout")

# ---------- 3. 大文件 / 搜索 ----------
section("files")


def call(cap, **a):
    return capabilities.run([CapabilityInput("c", cap, "{}", a)])[0].content


root = tempfile.mkdtemp(prefix="spirit-stress-files-")
config.set("engine.workdir", root)
capabilities.rebind()
big = os.path.join(root, "big.txt")
call("writeFile", path=big, content="A" * (900 * 1024))
out = call("readFile", path=big, limit=5)
assert "共 1 行" in out
for i in range(100):
    with open(os.path.join(root, f"f{i}.py"), "w", encoding="utf-8") as f:
        f.write(f"def f{i}():\n    return {i}\n")
out = call("searchFiles", pattern="return 42", path=root, glob="*.py")
assert "f42.py" in out, out[:200]
out = call("findFiles", name="f5*.py", path=root)
assert "f50.py" in out
print("big file + search ok")
ok.append("files 900KB + 100 files")

# ---------- 4. 会话索引 / 切换 ----------
section("sessions")
for i in range(10):
    path = os.path.join(SESSION_DIR, f"session-20261118-1200{i:02d}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"seq": 1, "address": "user", "payload": f"历史 {i}"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"seq": 2, "address": "assistant", "payload": f"回复 {i}"}, ensure_ascii=False) + "\n")

engine = Engine(workdir=root)
sessions = engine.list_sessions()
assert len(sessions) == 10, len(sessions)
for item in sessions:
    events = engine.load_session(item["path"])
    assert len(events) == 2, events
assert engine.new_session() == []
assert engine.list_sessions()[0]["title"].startswith("历史")
print("10 sessions switch ok")
ok.append("sessions 10 switch")

# ---------- 5. 后台进程 ----------
section("processes")
pids = []
for i in range(5):
    out = call("processStart", command=f"sleep 30; echo {i}")
    pids.append(out.split()[1].split("（")[0])
for pid in pids:
    out = call("processKill", id=pid)
    assert "已结束" in out, out
listing = call("processList")
assert listing.count("已结束") >= 5
print("5 processes killed")
ok.append("process 5")

# ---------- 6. SSE 广播 ----------
section("sse broadcast")
subs = [Output.subscribe() for _ in range(3)]
for i in range(200):
    Output.publish({"type": "x", "i": i})
for sub in subs:
    got = 0
    while True:
        try:
            sub.get_nowait()
            got += 1
        except Exception:
            break
    assert got == 200, got
    Output.unsubscribe(sub)
print("3 subscribers x 200 events")
ok.append("sse broadcast")

# ---------- 7. 假模型全链路（工具循环） ----------
section("fake model loop")
target = os.path.join(root, "target.txt")
with open(target, "w", encoding="utf-8") as f:
    f.write("spirit\n")

calls = {"n": 0}


def fake_create(handle, bundle, schemas, thinking_on, effort="medium"):
    calls["n"] += 1
    if calls["n"] == 1:
        item = NS(type="function_call", call_id="call_1", name="readFile",
                  arguments=json.dumps({"path": target}))
        return iter([NS(type="response.completed", response=NS(output=[item]))])
    return iter([
        NS(type="response.output_text.delta", delta="读完了"),
        NS(type="response.completed", response=NS(output=[])),
    ])


original = adapter.create
adapter.create = fake_create
try:
    msgs = ["读一下 target.txt"]
    def source():
        if msgs:
            return msgs.pop(0)
        raise EOFError
    engine.set_input_source(source)
    assert engine.start()
    engine.run()
finally:
    adapter.create = original

mem.flush()
addresses = [r.address for r in mem.records()]
assert "tool_call" in addresses and "tool_output" in addresses, addresses
tool_outputs = [r.payload["output"] for r in mem.records() if r.address == TOOL_OUTPUT]
assert any("spirit" in str(o) for o in tool_outputs), tool_outputs
assert any(r.address == "assistant" and r.payload == "读完了" for r in mem.records())
print("fake model tool loop ok, calls:", calls["n"])
ok.append("fake model loop")

# ---------- 8. 重复启停 ----------
section("engine restart")
for _ in range(3):
    e = Engine(workdir=root)
    e.set_input_source(lambda: (_ for _ in ()).throw(EOFError))
    assert e.start()
    e.run()
print("3 start/stop cycles")
ok.append("engine restart x3")

print("\nSTRESS OK:", ", ".join(ok))
