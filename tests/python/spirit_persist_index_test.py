"""会话文件稀疏行偏移索引：区间读 / 老文件建索引 / 追加后索引更新。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-index-home-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Engine import Engine  # noqa: E402
from Memory import mem, USER  # noqa: E402
from Memory.Persist import INDEX_STRIDE, persist  # noqa: E402
from Render import render  # noqa: E402

engine = Engine(home=home, workdir=Path(tempfile.mkdtemp()))
engine.start()
render.set_console(False)

TOTAL = 2000
for i in range(TOTAL):
    mem.submit(USER, f"消息{i}")
mem.flush()
assert persist.save() is not None
path = Path(persist.current_path)
meta = json.loads(Path(str(path) + ".meta.json").read_text(encoding="utf-8"))
anchors = dict(meta.get("anchors") or [])
assert meta.get("lines") == TOTAL, (meta.get("lines"), TOTAL)
assert anchors.get(1) == 0, anchors
assert anchors.get(1 + INDEX_STRIDE), "应该有第二个锚点"
print("1. 索引写入 ok:", len(anchors), "个锚点")

# 区间读：只要最近 5 轮，不能从第 1 行开始解析
tail = persist.read_records(limit_turns=5)
assert tail, "区间读没有结果"
assert tail[0].seq > TOTAL // 2, f"从第 {tail[0].seq} 条开始，说明没走区间读"
assert sum(1 for record in tail if record.address == "user") >= 5
print("2. 区间读 ok: 起点 seq =", tail[0].seq)

# 全量读仍然完整
full = persist.read_records()
assert len(full) == TOTAL, len(full)
print("3. 全量读 ok")

# 追加后行数 / 锚点更新
for i in range(100):
    mem.submit(USER, f"追加{i}")
mem.flush()
assert persist.save() is not None
meta = json.loads(Path(str(path) + ".meta.json").read_text(encoding="utf-8"))
assert meta.get("lines") == TOTAL + 100, meta.get("lines")
again = persist.read_records()
assert len(again) == TOTAL + 100, len(again)
print("4. 追加后索引更新 ok")

# 没有 sidecar 的老文件：扫一遍建索引再读
legacy = home / "session-legacy.jsonl"
lines = [
    json.dumps({"seq": i + 1, "address": "user", "payload": f"老{i}"}, ensure_ascii=False)
    for i in range(1200)
]
legacy.write_text("\n".join(lines) + "\n", encoding="utf-8")
old_tail = persist.read_records(limit_turns=3, path=legacy)
assert old_tail and old_tail[0].seq > 600, old_tail[0].seq if old_tail else None
print("5. 老文件建索引 ok")

# ---------- 6. rename 不占序号：之后保存不会撞 seq ----------
mem.clear()
persist.reset()
mem.submit(USER, "一")
mem.submit("assistant", "二")
mem.flush()
assert persist.save() is not None
path2 = persist.current_path
persist.rename(path2, "改过的标题")
mem.submit(USER, "三")
mem.flush()
assert persist.save() is not None
lines = [json.loads(line) for line in open(path2, encoding="utf-8") if line.strip()]
seqs = [item["seq"] for item in lines]
assert len(seqs) == len(set(seqs)), seqs
assert seqs[-1] == 3, seqs
print("6. rename 不撞 seq ok")

# ---------- 7. 索引命中后列表不再扫文件 ----------
from Memory.Persist import PersistSystem  # noqa: E402
persist.list_sessions()          # 先让所有老会话补写一次索引
PersistSystem._PersistSystem__summary = staticmethod(
    lambda path: (_ for _ in ()).throw(AssertionError("有索引时不应扫 JSONL"))
)
items = persist.list_sessions()
assert any(item["title"] == "改过的标题" for item in items), items
print("7. 列表走索引 ok")

render.shutdown()
print("\nPERSIST INDEX TEST OK")
