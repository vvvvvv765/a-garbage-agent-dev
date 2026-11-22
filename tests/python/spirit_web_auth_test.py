"""本地控制面安全：令牌 + Host 校验 + 会话路径围栏 + 导出确认。

对应评审 P0：DNS rebinding / 本机任意进程读 Key / 删任意文件。
"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR",
             "SPIRIT_WEB_AUTH", "SPIRIT_API_TOKEN"):
    os.environ.pop(name, None)

from Engine import Engine  # noqa: E402
from WebUI import server as web  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-auth-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-auth-work-"))
engine = Engine(home=home, workdir=work)
web._engine = engine

# ---------- 1. 页面注入令牌 ----------
html = web.app.test_client().get("/").get_data(as_text=True)
assert 'name="spirit-api-token"' in html, "页面没有注入令牌"
print("1. 页面注入令牌 ok")

# ---------- 2. 无令牌 / 错令牌 → 401 ----------
raw = web.app.test_client()
assert raw.get("/api/status").status_code == 200   # 健康检查豁免（桌面壳靠它判断起没起）
assert raw.get("/api/providers").status_code == 401
assert raw.get("/api/providers", headers={"X-Spirit-Token": "wrong"}).status_code == 401
ok = web.test_client()
assert ok.get("/api/status").status_code == 200
assert raw.get(f"/api/providers?token={web.API_TOKEN}").status_code == 401   # 查询参数令牌只留给 SSE
print("2. 令牌校验 ok")

# ---------- 3. Host 校验（DNS rebinding） ----------
assert ok.get("/api/status", base_url="http://evil.example").status_code == 403
assert ok.get("/", base_url="http://evil.example").status_code == 403      # 首页也校验 Host
assert ok.get("/").status_code == 200
assert ok.get("/api/providers", headers={"Origin": "http://evil.example"}).status_code == 403
assert ok.get("/api/providers", headers={"Origin": "http://127.0.0.1:5000"}).status_code == 200
assert ok.get("/api/status", base_url="http://127.0.0.1:5000").status_code == 200
print("3. Host 校验 ok")

# ---------- 4. 会话路径围栏 ----------
outside = Path(tempfile.mkdtemp(prefix="spirit-auth-out-")) / "x.jsonl"
outside.write_text('{"seq":1,"address":"user","payload":"x"}\n', encoding="utf-8")
assert ok.post("/api/session", json={"path": str(outside)}).status_code == 400
assert ok.post("/api/session/delete", json={"path": str(outside)}).status_code == 400
assert ok.post("/api/session/rename", json={"path": str(outside), "title": "x"}).status_code == 400
assert outside.exists(), "围栏拒绝时不能删掉外部文件"
inside = Path(engine.session_dir) / "session-20200101-000000.jsonl"
inside.parent.mkdir(parents=True, exist_ok=True)
inside.write_text('{"seq":1,"address":"user","payload":"hi"}\n', encoding="utf-8")
assert ok.post("/api/session", json={"path": str(inside)}).status_code == 200
print("4. 会话路径围栏 ok")

# ---------- 5. 导出需要显式确认 ----------
assert ok.post("/api/providers/export").status_code == 400
res = ok.post("/api/providers/export", json={"confirm": True}).get_json()
assert res["ok"] and res["format"] == "spirit-providers", res
print("5. 导出确认 ok")

# ---------- 6. 审批答复：remember 透传给引擎 ----------
import queue as queue_mod  # noqa: E402

answer = queue_mod.Queue(maxsize=1)
with web._pending_lock:
    web._pending["test-approval"] = (answer, {"kind": "access", "path": r"D:\x"})
res = ok.post("/api/approval", json={"id": "test-approval", "allow": True, "remember": True}).get_json()
assert res["ok"], res
assert answer.get_nowait() == {"allow": True, "remember": True}
res = ok.post("/api/approval", json={"id": "test-approval", "allow": True})
assert res.status_code == 404, res.get_json()
print("6. 审批 remember 透传 ok")

print("ALL WEB AUTH TESTS PASSED")
