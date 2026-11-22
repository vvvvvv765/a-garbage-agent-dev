"""不可信内容策略：设置接口能改，且立即影响审批。"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
sys.path.insert(0, str(root))
home = Path(tempfile.mkdtemp(prefix="spirit-untrusted-api-"))
work = Path(tempfile.mkdtemp(prefix="spirit-untrusted-api-work-"))
os.environ["SPIRIT_HOME"] = str(home)
for name in ("SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
import WebUI.server as server  # noqa: E402

engine = Engine(home=home, workdir=work)
server._engine = engine
client = server.test_client()

# ---------- 1. 默认 confirm ----------
data = client.get("/api/settings").get_json()
assert data["untrusted_policy"] == "confirm", data.get("untrusted_policy")
print("default confirm ok")

# ---------- 2. 改成 warn：落盘 ----------
response = client.post("/api/settings", json={"untrusted_policy": "warn"})
assert response.status_code == 200, response.status_code
assert response.get_json()["untrusted_policy"] == "warn"
saved = json.loads((home / "config.json").read_text(encoding="utf-8"))
assert saved["engine"]["untrusted_policy"] == "warn"
print("persist warn ok")

# ---------- 3. 立即生效：auto 模式下，不可信内容之后的写不再问 ----------
config.set("engine.approval", "auto")
calls = []
security.set_approver(lambda request: calls.append(request) or (True, "ok"))
security.note_untrusted("bash")
allowed, reason = security.check("writeFile", "{}", "c1")
assert allowed is True, (allowed, reason)
assert calls == [], "warn 时不应该弹审批"
security.clear_untrusted()
print("warn bypass ok")

# ---------- 4. 改回 confirm：自动模式下仍然不问（完全自动） ----------
response = client.post("/api/settings", json={"untrusted_policy": "confirm"})
assert response.status_code == 200
security.note_untrusted("bash")
allowed, reason = security.check("writeFile", "{}", "c2")
assert allowed is True and calls == [], (allowed, calls)
security.clear_untrusted()
print("confirm bypass in auto ok")

# ---------- 4b. 「阻止」是显式策略，仍然生效 ----------
response = client.post("/api/settings", json={"untrusted_policy": "block"})
assert response.status_code == 200
security.note_untrusted("bash")
allowed, reason = security.check("writeFile", "{}", "c3")
assert allowed is False and "阻止" in reason, (allowed, reason)
security.clear_untrusted()
print("block still blocks ok")

# ---------- 5. 非法值拒绝 ----------
response = client.post("/api/settings", json={"untrusted_policy": "whatever"})
assert response.status_code == 400, response.status_code
print("invalid rejected ok")

print("ALL UNTRUSTED POLICY API TESTS PASSED")
