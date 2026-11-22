"""权限两轴：范围（查看 / 可修改）× 模式（询问 / 自动）。

2026-11-19 他要求把「工作区内修改 / 每次确认 / 完全放行」拆成两件事：
  - 范围：能碰什么（查看 = 写类直接拒绝；可修改 = 允许，路径仍受沙箱）
  - 模式：碰的时候问不问（询问 = 写与外部要确认；自动 = 不问）
"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-perm-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-perm-work-"))
engine = Engine(home=home, workdir=work)

EFFECTS = {"readFile": "read", "listDir": "read", "writeFile": "write",
           "bash": "write", "fetchUrl": "external", "webSearch": "external"}
security.set_side_effect_resolver(lambda name: EFFECTS.get(name, "write"))

asked = []


def approver(request):
    asked.append(request["name"])
    return True


security.set_approver(approver)

# ---------- 1. 旧模式值归一 ----------
assert engine.set_approval("rules") == "ask"
assert engine.set_approval("manual") == "ask"
assert engine.set_approval("auto") == "auto"
assert engine.set_approval("ask") == "ask"
try:
    engine.set_approval("nonsense")
    raise AssertionError("未知模式应报错")
except ValueError:
    pass
print("1. 模式归一 ok")

# ---------- 2. 询问模式：读不问，写 / 外部门 ----------
asked.clear()
assert security.check("readFile", "a")[0] is True and not asked
allowed, reason = security.check("writeFile", "b")
assert allowed and asked == ["writeFile"], (allowed, reason, asked)
asked.clear()
allowed, reason = security.check("fetchUrl", "https://x")
assert allowed and asked == ["fetchUrl"], (allowed, asked)
print("2. 询问模式 ok")

# ---------- 3. 自动模式：都不问 ----------
engine.set_approval("auto")
asked.clear()
assert security.check("writeFile", "c")[0] is True
assert security.check("fetchUrl", "d")[0] is True
assert asked == [], asked
print("3. 自动模式 ok")

# ---------- 4. 查看范围：写类直接拒绝，且不弹审批 ----------
engine.set_approval("ask")
engine.set_access("readonly")
asked.clear()
allowed, reason = security.check("writeFile", "e")
assert allowed is False and "查看" in reason, (allowed, reason)
assert asked == [], "查看范围下不该弹审批"
allowed, reason = security.check("bash", "ls")
assert allowed is False and asked == [], (allowed, reason)
# 读 / 外部仍放行；外部在询问模式要问
asked.clear()
assert security.check("readFile", "f")[0] is True and asked == []
allowed, reason = security.check("fetchUrl", "https://x")
assert allowed and asked == ["fetchUrl"], (allowed, asked)
# 自动模式 + 查看：写仍拒绝（范围优先于模式）
engine.set_approval("auto")
assert security.check("writeFile", "g")[0] is False
print("4. 查看范围 ok")

# ---------- 5. 可修改范围恢复 ----------
engine.set_access("workspace")
engine.set_approval("ask")
assert security.check("writeFile", "h")[0] is True
assert config.get("engine.access") == "workspace"
try:
    engine.set_access("full")
    raise AssertionError("未知范围应报错")
except ValueError:
    pass
print("5. 可修改范围 ok")

# ---------- 5b. 可访问路径（allow_paths，可选边界） ----------
config.set("engine.sandbox.workspace_only", True)
engine.reload_sandbox()
from Capabilities.Sandbox import SandboxDenied, sandbox  # noqa: E402

extra = Path(tempfile.mkdtemp(prefix="spirit-perm-extra-"))
(extra / "note.txt").write_text("ok", encoding="utf-8")
paths = engine.set_sandbox_paths([str(extra)])
assert paths == [str(extra.resolve())], paths
assert sandbox.resolve(str(work), str(extra / "note.txt")) == (extra / "note.txt").resolve()
outside = Path(tempfile.mkdtemp(prefix="spirit-perm-out-"))
try:
    sandbox.resolve(str(work), str(outside / "x.txt"))
    raise AssertionError("不在允许范围的路径应被拒绝")
except SandboxDenied:
    pass
try:
    engine.set_sandbox_paths(["relative/path"])
    raise AssertionError("相对路径应报错")
except ValueError as error:
    assert "绝对路径" in str(error)
try:
    engine.set_sandbox_paths([str(outside / "missing")])
    raise AssertionError("不存在的路径应报错")
except ValueError as error:
    assert "不存在" in str(error)
print("5b. 可访问路径 ok")

# 查看范围的拒绝理由要带出路
engine.set_access("readonly")
allowed, reason = security.check("bash", "ls")
assert allowed is False and "readFile" in reason, reason
engine.set_access("workspace")
print("5c. 查看拒绝理由带指引 ok")

# ---------- 6. Web 接口 ----------
from WebUI import server as web  # noqa: E402
web._engine = engine
http = web.test_client()

payload = http.get("/api/settings").get_json()
assert payload["approval"] == "ask" and payload["access"] == "workspace", payload
res = http.post("/api/access-mode", json={"access": "readonly"}).get_json()
assert res["ok"] and res["access"] == "readonly", res
payload = http.get("/api/settings").get_json()
assert payload["access"] == "readonly"
res = http.post("/api/access-mode", json={"access": "nonsense"})
assert res.status_code == 400, res.get_json()
res = http.post("/api/approval-mode", json={"mode": "auto"}).get_json()
assert res["ok"] and res["approval"] == "auto", res
payload = http.get("/api/settings").get_json()
assert str(extra.resolve()) in payload["sandbox_paths"], payload["sandbox_paths"]
res = http.post("/api/sandbox/paths", json={"paths": []}).get_json()
assert res["ok"] and res["sandbox_paths"] == [], res
res = http.post("/api/sandbox/paths", json={"paths": ["nope"]})
assert res.status_code == 400, res.get_json()
print("6. Web 接口 ok")

print("ALL PERMISSION AXIS TESTS PASSED")
