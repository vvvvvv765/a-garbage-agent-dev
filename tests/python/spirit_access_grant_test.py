"""工作区外访问授权（批 K）：越界 → 问用户「允许本次」→ 只对这一批放行。

Claude 的做法是：不在允许范围里的路径，弹一次确认；允许就只对这次调用生效，
拒绝就返回错误。这里验证 Spirit 的三层都接上了：
  Sandbox（结构化拒绝 + once 授权）→ Security.request_access（走审批回调）
  → CPU.__run_tools（授权后重试预检，批末清掉 once）
"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-access-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC.CPU import DC as cpu  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-access-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-access-work-"))
outside = Path(tempfile.mkdtemp(prefix="spirit-access-out-"))
secret = outside / "secret.txt"
secret.write_text("工作区外的内容", encoding="utf-8")
outside_resolved = str(secret.resolve())

engine = Engine(home=home, workdir=work)
config.set("engine.sandbox.workspace_only", True)
engine.reload_sandbox()
engine.set_access("workspace")
engine.set_approval("ask")
assert engine.start(), "引擎没有启动"

requests = []


def approver(request):
    requests.append(request)
    return global_allow[0]


global_allow = [True]
security.set_approver(approver)

# ---------- 1. 沙箱结构化拒绝：越界能分辨出来 ----------
ok, reason = capabilities.precheck("readFile", {"path": str(secret)})
assert ok is False and "不在工作区" in reason, (ok, reason)
info = capabilities.last_denial()
assert info.get("kind") == "outside", info
assert info.get("target") == outside_resolved, (info, outside_resolved)
print("1. 结构化拒绝 ok:", info["kind"])

# ---------- 2. 绝对禁止的拒绝不带授权入口 ----------
blocked = Path.home() / ".ssh" / "id_rsa"
capabilities.precheck("readFile", {"path": str(blocked)})
info = capabilities.last_denial()
assert info.get("kind") in ("protected", "denied"), info
assert info["kind"] != "outside", "禁止路径不该走到授权口"
print("2. 禁止路径不提供授权口 ok")

# ---------- 3. Security.request_access：字段齐、允许 / 拒绝都回 ----------
capabilities.precheck("readFile", {"path": str(secret)})
outside_info = capabilities.last_denial()
requests.clear()
assert security.request_access("readFile", "call-a", outside_info) is True
req = requests[-1]
assert req["kind"] == "access" and req["path"] == outside_resolved, req
assert "不在工作区" in req["reason"], req["reason"]
assert req["mode"] in ("ask", "auto") and req["access"] in ("readonly", "workspace"), req
global_allow[0] = False
assert security.request_access("readFile", "call-b", outside_info) is False
global_allow[0] = True
print("3. 访问请求字段与拒绝 ok")

# ---------- 4. once 授权：只覆盖当前，clear 后恢复拒绝 ----------
capabilities.grant_once(outside_resolved)
ok, _ = capabilities.precheck("readFile", {"path": str(secret)})
assert ok is True, "grant_once 之后应该放行"
capabilities.clear_once()
ok, _ = capabilities.precheck("readFile", {"path": str(secret)})
assert ok is False, "clear_once 之后应该恢复拒绝"
print("4. once 授权生命周期 ok")

# ---------- 5. CPU 全链路：问 → 放行 → 真读到；批末清掉 ----------
requests.clear()
outs = cpu._CPU__run_tools([{
    "call_id": "call-1",
    "name": "readFile",
    "arguments": json.dumps({"path": str(secret)}, ensure_ascii=False),
}])
assert len(outs) == 1 and outs[0].ok, (outs and outs[0].content)
assert "工作区外的内容" in outs[0].content, outs[0].content
assert requests and requests[-1]["kind"] == "access", requests
assert requests[-1]["path"] == outside_resolved
assert capabilities.precheck("readFile", {"path": str(secret)})[0] is False, \
    "批末应该清掉 once 授权"
print("5. CPU 授权后重试 ok")

# ---------- 5b. 允许本次之后不再重复弹审批（写文件只弹一次访问请求） ----------
target2 = outside / "write-me.txt"
requests.clear()
outs = cpu._CPU__run_tools([{
    "call_id": "call-w1",
    "name": "writeFile",
    "arguments": json.dumps({"path": str(target2), "content": "写进去了"}, ensure_ascii=False),
}])
assert outs and outs[0].ok, (outs and outs[0].content)
assert target2.read_text(encoding="utf-8") == "写进去了"
assert [item["kind"] for item in requests] == ["access"], requests
print("5b. 访问授权后不再重复弹审批 ok")

# ---------- 5c. 但「查看」范围仍然压过访问授权 ----------
engine.set_access("readonly")
target3 = outside / "readonly.txt"
requests.clear()
outs = cpu._CPU__run_tools([{
    "call_id": "call-w2",
    "name": "writeFile",
    "arguments": json.dumps({"path": str(target3), "content": "不该写"}, ensure_ascii=False),
}])
engine.set_access("workspace")
assert outs and not outs[0].ok, (outs and outs[0].content)
assert "查看" in outs[0].content, outs[0].content
assert not target3.exists(), "查看范围下不该落盘"
print("5c. 查看范围仍然生效 ok")

# ---------- 6. 拒绝时把沙箱原因交回模型，不执行 ----------
requests.clear()
global_allow[0] = False
outs = cpu._CPU__run_tools([{
    "call_id": "call-2",
    "name": "readFile",
    "arguments": json.dumps({"path": str(secret)}, ensure_ascii=False),
}])
global_allow[0] = True
assert outs and not outs[0].ok, outs[0].content if outs else None
assert "沙箱拒绝" in outs[0].content, outs[0].content
assert requests and requests[-1]["kind"] == "access", requests
print("6. 拒绝结果回到模型 ok")

# ---------- 7. 长期允许：加进「可访问的路径」后不再问 ----------
secret2 = outside / "secret2.txt"
secret2.write_text("第二个文件", encoding="utf-8")
requests.clear()
assert engine.set_sandbox_paths([str(outside)]) == [str(outside.resolve())]
outs = cpu._CPU__run_tools([{
    "call_id": "call-3",
    "name": "readFile",
    "arguments": json.dumps({"path": str(secret2)}, ensure_ascii=False),
}])
assert outs and outs[0].ok, (outs and outs[0].content)
assert requests == [], "已加进可访问路径就不该再问"
engine.set_sandbox_paths([])
print("7. 可访问路径长期授权 ok")

# ---------- 8. 会话级授权：clear_once 不影响它 ----------
capabilities.grant_session(outside_resolved)
capabilities.clear_once()
assert capabilities.precheck("readFile", {"path": str(secret)})[0] is True
print("8. 会话级授权 ok")

# ---------- 9. 本次运行都允许：批末 clear_once 也还在 ----------
secret3 = outside / "secret3.txt"
secret3.write_text("第三个文件", encoding="utf-8")


def session_approver(request):
    requests.append(request)
    return True, "用户允许本次运行", "session"


security.set_approver(session_approver)
requests.clear()
outs = cpu._CPU__run_tools([{
    "call_id": "call-s1",
    "name": "readFile",
    "arguments": json.dumps({"path": str(secret3)}, ensure_ascii=False),
}])
assert outs and outs[0].ok, (outs and outs[0].content)
assert security.access_scope == "session", security.access_scope
assert capabilities.precheck("readFile", {"path": str(secret3)})[0] is True, "会话级授权不该被批末清掉"
print("9. 本次运行都允许 ok")

print("\nALL ACCESS GRANT TESTS PASSED")
