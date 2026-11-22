"""会话切换守卫：轮次处理中拒绝切会话 / 新会话 / 删当前会话（Web 409）。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-guard-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-guard-work-"))
os.environ["SPIRIT_HOME"] = str(home)
for name in ("SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from DC import DC  # noqa: E402
from Engine import Engine  # noqa: E402

engine = Engine(home=home, workdir=work)
assert engine.start(), "engine not started"


def raises(action):
    try:
        action()
    except RuntimeError as error:
        assert "还在处理" in str(error), error
        return str(error)
    raise AssertionError("轮次处理中应该拒绝")


# ---------- 1. 轮次处理中：三个入口全部拒绝 ----------
DC.turn_active = True
try:
    raises(engine.new_session)
    raises(engine.clear_memory)
    raises(lambda: engine.load_session("whatever.jsonl"))
finally:
    DC.turn_active = False
print("busy rejection ok")

# ---------- 2. 空闲：可以新建 / 载入 ----------
assert engine.new_session() == []
session = home / "Session_Storage" / "session-20260101-000000.jsonl"
session.parent.mkdir(parents=True, exist_ok=True)
session.write_text(
    "\n".join([
        json.dumps({"seq": 1, "address": "user", "payload": "旧问题"}, ensure_ascii=False),
        json.dumps({"seq": 2, "address": "assistant", "payload": "旧回答"}, ensure_ascii=False),
    ]) + "\n",
    encoding="utf-8",
)
events = engine.load_session(str(session))
assert [e["type"] for e in events] == ["user_message", "assistant_message"], events
assert engine.current_session() == str(session)
print("idle switch ok")

# ---------- 3. 处理中删“当前会话”也要拒绝（否则会顺带清表） ----------
DC.turn_active = True
try:
    raises(lambda: engine.delete_session(str(session)))
finally:
    DC.turn_active = False
assert session.exists(), "被拒绝时不能删文件"
print("busy delete blocked ok")

# ---------- 4. Web 路由映射成 409 ----------
import WebUI.server as server  # noqa: E402

server._engine = engine
client = server.test_client()

DC.turn_active = True
try:
    # K4b：主会话忙时新建 → 开独立运行时，不再 409
    response = client.post("/api/session", json={"new": True})
    assert response.status_code == 200, response.status_code
    data = response.get_json()
    assert data["ok"] and data["session"] != "primary", data
    # 切回主会话看历史也不受“忙”影响
    response = client.post("/api/session", json={"path": str(session)})
    assert response.status_code == 200, response.status_code
    assert response.get_json()["session"] == "primary"
finally:
    DC.turn_active = False

response = client.post("/api/session", json={"new": True})
assert response.status_code == 200, response.status_code
assert response.get_json()["ok"] is True
engine.stop()
print("web multi-session routing ok")

print("ALL SESSION GUARD TESTS PASSED")
