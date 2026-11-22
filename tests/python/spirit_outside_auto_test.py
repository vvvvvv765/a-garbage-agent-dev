"""工作区外访问「自动允许」设置：开了就不再逐条问，但禁止路径仍然拒绝。"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-auto-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from DC.CPU import DC as cpu  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-auto-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-auto-work-"))
outside = Path(tempfile.mkdtemp(prefix="spirit-auto-out-"))
(outside / "a.txt").write_text("ok", encoding="utf-8")
engine = Engine(home=home, workdir=work)
config.set("engine.sandbox.workspace_only", True)
engine.reload_sandbox()
engine.set_approval("ask")
assert engine.start()

asked = []
security.set_approver(lambda request: asked.append(request) or True)
config.set("engine.sandbox.auto_allow_outside", False)


def read(path, cid):
    return cpu._CPU__run_tools([{
        "call_id": cid,
        "name": "readFile",
        "arguments": json.dumps({"path": str(path)}, ensure_ascii=False),
    }])[0]


# 1. 关闭：仍然问一次
out = read(outside / "a.txt", "auto-1")
assert out.ok, out.content
assert asked and asked[-1]["kind"] == "access", asked
print("1. 关闭时仍询问 ok")

# 2. 开启：直接放行，不打扰
config.set("engine.sandbox.auto_allow_outside", True)
asked.clear()
(outside / "b.txt").write_text("ok", encoding="utf-8")
out = read(outside / "b.txt", "auto-2")
assert out.ok, out.content
assert asked == [], asked
print("2. 开启后不再询问 ok")

# 2b. 自动模式：工作区外直接放行，也不打扰
engine.set_approval("auto")
config.set("engine.sandbox.auto_allow_outside", False)
asked.clear()
(outside / "c.txt").write_text("ok", encoding="utf-8")
out = read(outside / "c.txt", "auto-2b")
assert out.ok, out.content
assert asked == [], asked
print("2b. 自动模式越界不询问 ok")
engine.set_approval("ask")

# 3. 禁止路径不受影响
asked.clear()
blocked = Path.home() / ".ssh" / "id_rsa"
out = read(blocked, "auto-3")
assert not out.ok and "沙箱拒绝" in out.content, out.content
assert asked == [], asked
print("3. 禁止路径仍拒绝 ok")

# 4. Web 设置读写
from WebUI import server as web  # noqa: E402

web._engine = engine
http = web.test_client()
config.set("engine.sandbox.auto_allow_outside", True)
payload = http.get("/api/settings").get_json()
assert payload["auto_allow_outside"] is True, payload
res = http.post("/api/settings", json={"auto_allow_outside": False}).get_json()
assert res["ok"] and res["auto_allow_outside"] is False, res
assert config.get("engine.sandbox.auto_allow_outside") is False
print("4. Web 设置 ok")

print("\nALL AUTO ALLOW OUTSIDE TESTS PASSED")
