"""轮次号 / 瞬态容量 / O(1) 水位 / 只读用量扫描 测试。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_HOME"] = tempfile.mkdtemp(prefix="spirit-turn-home-")
for name in ("SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from DC.Guard import guard  # noqa: E402
from DC.Security import security  # noqa: E402
from Memory import mem, USER, USAGE, STREAM  # noqa: E402
from Memory.Memory import TRANSIENT_MAXLEN  # noqa: E402
from Paths import log_dir  # noqa: E402
from Render import render  # noqa: E402
from Turn import turn  # noqa: E402
from Usage import report  # noqa: E402

# ---------- 1. 轮次号：只在 CPU 轮次边界递增 ----------
first = turn.begin()
second = turn.begin()
assert second == first + 1, (first, second)
assert turn.current() == second
print("turn counter ok")

# ---------- 2. 数据表记录带上写入时的轮次号 ----------
mem.clear()
current = turn.begin()
mem.submit(USER, "你好")
mem.flush()
assert mem.records()[-1].turn == current, mem.records()[-1]
print("record turn ok")

# ---------- 3. O(1) 水位：整表 / 单地址 ----------
total = mem.last_seq()
assert total == len(mem.records()) == mem.records()[-1].seq, (total, len(mem.records()))
assert mem.last_seq(USER) == mem.records()[-1].seq
assert mem.last_seq(USAGE) == 0
print("last_seq ok")

# ---------- 4. 瞬态地址容量兜底 ----------
mem.clear()
for index in range(TRANSIENT_MAXLEN + 50):
    mem.push_transient(STREAM, {"delta": str(index)})
items = mem.transient(STREAM)
assert len(items) == TRANSIENT_MAXLEN, len(items)
assert items[0]["delta"] == "50", items[0]
mem.clear_transient(STREAM)
assert mem.transient(STREAM) == []
print("transient cap ok:", TRANSIENT_MAXLEN)

# ---------- 5. 只扫 usage 记录 == 全表扫描（结果一致） ----------
mem.clear()
turn.begin()
mem.submit(USER, "第一轮")
mem.submit(USAGE, {
    "input": 100, "output": 50, "total": 150,
    "cached": 0, "reasoning": 0, "purpose": "chat", "priced": False,
})
mem.submit(USER, "第二轮")
mem.submit(USAGE, {
    "input": 200, "output": 100, "total": 300,
    "cached": 100, "reasoning": 0, "purpose": "chat", "priced": False,
})
mem.flush()

full = report(mem.records())
fast = report(mem.view(USAGE), last_user=mem.last_seq(USER))
assert full == fast, (full, fast)
assert fast["session"]["total"] == 450, fast["session"]
assert fast["turn"]["total"] == 300, fast["turn"]
print("usage scan equivalence ok")

# ---------- 6. 循环守卫走的就是这条快路 ----------
config.set("engine.max_turn_tokens", 1)
assert "本轮 token" in guard.budget_stop(), guard.budget_stop()
config.set("engine.max_turn_tokens", 0)
assert guard.budget_stop() == ""
print("guard budget ok")

# ---------- 7. 审计带轮次号 ----------
ok, _ = security.check("readFile", "{}", "call-turn")
assert ok is True
audit = log_dir() / "audit.jsonl"
last = json.loads(audit.read_text(encoding="utf-8").strip().splitlines()[-1])
assert last["turn"] == turn.current(), last
print("audit turn ok")

# ---------- 8. 渲染实时事件带轮次号 ----------
render.set_console(False)
events = []
render.add_sink(events.append)
render.assistant_delta("测试")
assert events and events[-1].get("turn") == turn.current(), events[-1]
print("render event turn ok")

print("ALL TURN / SCAN TESTS PASSED")
