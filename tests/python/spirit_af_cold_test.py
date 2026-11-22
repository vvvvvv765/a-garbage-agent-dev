"""AF：摘要驱动的冷记录退役 / 磁盘回放 / 懒加载 / 用量不丢。"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-af-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-af-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import mem, USER, ASSISTANT, REASONING, SUMMARY, USAGE  # noqa: E402
from Memory.Persist import persist as persist_system  # noqa: E402
from Render import render  # noqa: E402

engine = Engine(home=home, workdir=work)
engine.start()
render.set_console(False)

# ---------- 1. 造长会话 + 一条摘要 ----------
for i in range(30):
    mem.submit(USER, f"问题{i}")
    mem.submit(REASONING, {"type": "thinking", "thinking": "想", "signature": "s", "_dialect": "anthropic"})
    mem.submit(ASSISTANT, f"答{i}")
mem.submit(USAGE, {"input": 10, "output": 5, "total": 15, "purpose": "chat",
                   "model": "m", "provider": "p", "cost": 0, "priced": False, "currency": "CNY"})
mem.flush()
records = mem.records()
summary_end = records[60].seq          # 覆盖前 20 轮左右
mem.submit(SUMMARY, {"text": "之前聊过一些东西", "start_seq": 1, "end_seq": summary_end})
mem.flush()
persist = persist_system
assert persist.save() is not None      # 必须先落盘，退役才有依据

# ---------- 2. 构建上下文触发退役 ----------
gpu.build_context(compact=False)
print("floor =", mem.records_floor(), "summary_end =", summary_end, "last_seq =", mem.last_seq())
assert mem.records_floor() == summary_end
assert all(r.seq > summary_end for r in mem.records()), "主表还有冷记录"
assert mem.view(SUMMARY), "摘要视图被退役清掉了"
assert any(r.address == USAGE for r in mem.view(USAGE)), "用量视图被退役清掉了"
print("1/2. 冷记录退役 ok")

# ---------- 3. 用量不丢 ----------
session = engine.usage()["session"]
assert session["input"] == 10 and session["requests"] == 1, session
print("3. 退役后用量仍完整 ok")

# ---------- 4. 水位 / 新记录编号 ----------
after = mem.records_after(summary_end)
assert after and after[0].seq == summary_end + 1
mark = mem.last_seq()
mem.submit(USER, "退役后的一条")
mem.flush()
assert mem.last_seq() == mark + 1, (mark, mem.last_seq())
print("4. 水位与新编号 ok")

# ---------- 5. 回放要更早：从磁盘补冷记录 ----------
window = engine.history_window(25)
users = [ev for ev in window["events"] if ev["type"] == "user_message"]
assert len(users) == 25, len(users)
assert users[0]["text"] == "问题6", users[0]["text"]   # 31 条 user，取最后 25 条
assert window["has_more"] is True
print("5. 磁盘回放 ok")

# ---------- 6. 懒加载：重载只铺热记录，视图保留小记录 ----------
assert persist.save() is not None        # 新记录也要先落盘
path = persist.current_path
last = mem.last_seq()
mem.clear()
persist.reset()
persist.load(path)
assert mem.records_floor() == summary_end, (mem.records_floor(), summary_end)
assert all(r.seq > summary_end for r in mem.records())
assert mem.last_seq() == last, (mem.last_seq(), last)
assert any(r.address == USAGE for r in mem.view(USAGE))
assert mem.view(SUMMARY)
assert engine.usage()["session"]["input"] == 10
print("6. 懒加载 ok")

render.shutdown()
print("\nAF COLD TEST OK")
