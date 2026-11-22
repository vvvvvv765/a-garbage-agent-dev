"""渗透授权范围 API + 前端入口静态检查。"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
sys.path.insert(0, str(root))
home = Path(tempfile.mkdtemp(prefix="spirit-scope-api-"))
work = Path(tempfile.mkdtemp(prefix="spirit-scope-api-work-"))
os.environ["SPIRIT_HOME"] = str(home)
for name in ("SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from DC import DC  # noqa: E402
from Engine import Engine  # noqa: E402
import WebUI.server as server  # noqa: E402

engine = Engine(home=home, workdir=work)
server._engine = engine
client = server.test_client()

# ---------- 1. 默认空 ----------
data = client.get("/api/scope").get_json()
assert data["ok"] is True and data["scope"] == [], data
print("default empty ok")

# ---------- 2. 保存 / 去空白 / 去重 ----------
response = client.post("/api/scope", json={"scope": [" xy-api.example.edu.cn ", "", "xy-api.example.edu.cn", "10.0.0.5"]})
assert response.status_code == 200, response.status_code
data = response.get_json()
assert data["scope"] == ["xy-api.example.edu.cn", "10.0.0.5"], data
print("save ok")

# ---------- 3. 落盘 ----------
saved = json.loads((home / "config.json").read_text(encoding="utf-8"))
assert saved["engine"]["pentest_scope"] == ["xy-api.example.edu.cn", "10.0.0.5"], saved["engine"]
print("persisted ok")

# ---------- 4. 文本形态也收 ----------
data = client.post("/api/scope", json={"text": "a.example\nb.example\n"}).get_json()
assert data["scope"] == ["a.example", "b.example"], data
print("text form ok")

# ---------- 5. 轮次处理中拒绝 ----------
DC.turn_active = True
try:
    response = client.post("/api/scope", json={"scope": ["x.example"]})
    assert response.status_code == 409, response.status_code
    assert response.get_json()["ok"] is False
finally:
    DC.turn_active = False
print("busy 409 ok")

# ---------- 5.5 通配符 / 网段写法；非法网段拒绝 ----------
data = client.post(
    "/api/scope",
    json={"scope": ["*.sccc.edu.cn", "192.168.170.0/24"]},
).get_json()
assert data["ok"] is True and data["scope"] == ["*.sccc.edu.cn", "192.168.170.0/24"], data
response = client.post("/api/scope", json={"scope": ["10.0.0.0/33"]})
assert response.status_code == 400, response.status_code
print("wildcard / cidr ok")

# ---------- 6. 前端入口（场景浮层里的“授权范围”），窗口标题不带“新会话 ·” ----------
html = (root / "WebUI" / "static" / "index.html").read_text(encoding="utf-8")
assert 'id="scopeMask"' in html and 'id="scenarioPop"' in html
assert 'id="scopeBtn"' not in html          # 标题栏入口已移走
assert "<title>Spirit</title>" in html
js = (root / "WebUI" / "static" / "app.js").read_text(encoding="utf-8")
assert "'/api/scope'" in js and "updateScopeUI()" in js
assert "scenario-scope" in js and "openScopeDialog" in js
assert "新会话 · Spirit" not in js
main_ts = (root.parent / "desktop" / "src" / "main.ts").read_text(encoding="utf-8")
assert "title: 'Spirit'" in main_ts and "titleBarStyle: 'hidden'" in main_ts
print("ui wiring ok")

print("ALL SCOPE API TESTS PASSED")
