"""AE：有界队列 / 基础开销缓存 / 会话索引 sidecar / 回放窗口。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_MEMORY_QUEUE"] = "7"

home = Path(tempfile.mkdtemp(prefix="spirit-ae-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-ae-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import capabilities  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import mem, USER, ASSISTANT  # noqa: E402
from Memory.Persist import PersistSystem  # noqa: E402
from Render import render  # noqa: E402

engine = Engine(home=home, workdir=work)
engine.start()
render.set_console(False)

# ---------- 1. 有界提交队列 ----------
assert mem.queue_maxsize == 7, mem.queue_maxsize
print("1. 有界队列 ok:", mem.queue_maxsize)

# ---------- 2. 基础开销缓存：同一版本下不重复序列化工具定义 ----------
calls = {"n": 0}
original = capabilities.schemas

def counted():
    calls["n"] += 1
    return original()

capabilities.schemas = counted
config.set("engine.project_context", "缓存测试唯一串")
gpu.build_context(compact=False)
first = calls["n"]
gpu.build_context(compact=False)
second = calls["n"]
assert first >= 1, "第一次应该计算工具定义"
assert second == first, f"第二次不应重新序列化（{first} -> {second}）"
capabilities.schemas = original
print("2. 基础开销缓存 ok")

# ---------- 3. 会话索引 sidecar ----------
mem.submit(USER, "第一句话就是标题")
mem.submit(ASSISTANT, "答")
mem.flush()
persist = PersistSystem()
assert persist.save() is not None
meta_path = Path(str(persist.current_path) + ".meta.json")
meta = json.loads(meta_path.read_text(encoding="utf-8"))
assert meta["title"] == "第一句话就是标题", meta
assert meta["records"] == 2, meta

# 有索引就不许再扫文件
PersistSystem._PersistSystem__summary = staticmethod(
    lambda path: (_ for _ in ()).throw(AssertionError("有索引时不应扫 JSONL"))
)
items = persist.list_sessions()
assert items and items[0]["title"] == "第一句话就是标题", items
assert items[0]["records"] == 2, items
print("3. 会话索引 ok")

# ---------- 4. 回放窗口 ----------
mem.clear()
for i in range(50):
    mem.submit(USER, f"问题{i}")
    mem.submit(ASSISTANT, f"答{i}")
mem.flush()

window = engine.history_window(10)
users = [ev for ev in window["events"] if ev["type"] == "user_message"]
assert len(users) == 10, len(users)
assert users[-1]["text"] == "问题49", users[-1]
assert window["has_more"] is True

full = engine.history_window(200)
assert full["has_more"] is False
assert len([ev for ev in full["events"] if ev["type"] == "user_message"]) == 50
print("4. 回放窗口 ok")

# ---------- 5. Web 接口形状 ----------
from WebUI import server as web  # noqa: E402

web._engine = engine
http = web.test_client()
data = http.get("/api/history?limit=10").get_json()
assert data["has_more"] is True and data["limit"] == 10, data
assert len([ev for ev in data["events"] if ev["type"] == "user_message"]) == 10

switched = http.post("/api/session", json={"new": True, "limit": 10}).get_json()
assert switched["ok"] and switched["events"] == [] and switched["has_more"] is False, switched
print("5. Web 接口 ok")

print("\nAE TEST OK")
