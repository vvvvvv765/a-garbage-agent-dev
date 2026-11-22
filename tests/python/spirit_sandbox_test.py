"""沙箱 / 脱敏测试：路径边界、命令规则、环境清洗、审计打码。"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
from Paths import config_file, log_dir, session_dir  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-sandbox-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-sandbox-work-"))
outside = Path(tempfile.mkdtemp(prefix="spirit-sandbox-out-"))
(work / "inside.txt").write_text("inside", encoding="utf-8")
(outside / "secret.txt").write_text("outside", encoding="utf-8")
(work / "denied").mkdir()
(work / "denied" / "x.txt").write_text("denied", encoding="utf-8")

engine = Engine(home=home, workdir=work)
engine.set_approval("auto")

# 默认不再限制工作区；下面显式打开，继续验证这条可选边界
assert config.get("engine.sandbox.workspace_only") is False
config.set("engine.sandbox.workspace_only", True)
engine.reload_sandbox()


def precheck(name, arguments):
    return capabilities.precheck(name, arguments)


def run(name, arguments):
    raw = json.dumps(arguments, ensure_ascii=False)
    return capabilities.run([CapabilityInput("c-" + name, name, raw, arguments)])[0]


# ---------- 1. 路径边界 ----------
ok, reason = precheck("readFile", {"path": "inside.txt"})
assert ok, reason
ok, reason = precheck("readFile", {"path": str(outside / "secret.txt")})
assert not ok and "沙箱" in reason, reason
ok, reason = precheck("readFile", {"path": "../secret.txt"})
assert not ok, reason
ok, reason = precheck("writeFile", {"path": str(outside / "new.txt"), "content": "x"})
assert not ok, reason
out = run("readFile", {"path": str(outside / "secret.txt")})
assert not out.ok and "沙箱拒绝" in out.content, out.content
print("path boundary ok")

# ---------- 2. 引擎数据永远拒绝 ----------
assert precheck("readFile", {"path": str(config_file())})[0] is False
assert precheck("listDir", {"path": str(session_dir())})[0] is False
assert precheck("searchFiles", {"pattern": "key", "path": str(log_dir())})[0] is False
print("protected data ok")

# ---------- 3. 禁止路径 / 允许路径 ----------
config.set("engine.sandbox.deny_paths", ["*/denied/*"])
capabilities.reload_sandbox()
assert precheck("readFile", {"path": "denied/x.txt"})[0] is False
config.set("engine.sandbox.deny_paths", [])
config.set("engine.sandbox.allow_paths", [str(outside)])
capabilities.reload_sandbox()
assert precheck("readFile", {"path": str(outside / "secret.txt")})[0] is True
config.set("engine.sandbox.allow_paths", [])
capabilities.reload_sandbox()
print("deny/allow paths ok")

# ---------- 4. 命令规则 ----------
assert precheck("bash", {"bashinput": "rm -rf /"})[0] is False
assert precheck("bash", {"bashinput": "cd .."})[0] is True   # 只挡灾难，不挡正常导航
assert precheck("bash", {"bashinput": "echo ok"})[0] is True
assert precheck("processStart", {"command": "mkfs.ext4 /dev/sda"})[0] is False
out = run("bash", {"bashinput": "rm -rf /"})
assert not out.ok and "沙箱拒绝" in out.content, out.content
print("command policy ok")

# ---------- 5. bash 环境清洗 ----------
os.environ["DEEPSEEK_API_KEY"] = "sk-secret-env"
os.environ["SPIRIT_HOME"] = str(home)
out = run("bash", {"bashinput": 'echo "key=$DEEPSEEK_API_KEY home=$SPIRIT_HOME sandbox=$SPIRIT_SANDBOX"'})
assert "sk-secret-env" not in out.content, out.content
assert f"home={home}" not in out.content, out.content
assert "sandbox=workspace" in out.content, out.content
pwd = run("bash", {"bashinput": "pwd"})
assert "spirit-sandbox-work" in pwd.content.replace("\\", "/").lower(), pwd.content
print("bash env scrub ok:", out.content.strip())

# ---------- 6. 审计脱敏 ----------
security.set_approver(lambda request: True)
security.check(
    "writeFile",
    '{"text":"sk-abcdef123456","password":"hunter2","url":"https://x/?token=abc123"}',
    "call-redact",
)
audit = (log_dir() / "audit.jsonl").read_text(encoding="utf-8").splitlines()[-1]
assert "abcdef123456" not in audit, audit
assert "hunter2" not in audit, audit
assert "abc123" not in audit, audit
assert "***" in audit, audit
print("audit redaction ok")

# ---------- 7. 开关 ----------
config.set("engine.sandbox.workspace_only", False)
engine.reload_sandbox()
assert precheck("readFile", {"path": str(outside / "secret.txt")})[0] is True
assert precheck("readFile", {"path": str(config_file())})[0] is False  # 保护不随开关
config.set("engine.sandbox.workspace_only", True)
engine.reload_sandbox()
assert precheck("readFile", {"path": str(outside / "secret.txt")})[0] is False
print("workspace toggle ok")

# ---------- 8. 设置接口能切沙箱 ----------
import WebUI.server as server  # noqa: E402

server._engine = engine
api = server.test_client()
assert api.post("/api/settings", json={"sandbox_workspace": False}).get_json()[
    "sandbox_workspace"
] is False
assert precheck("readFile", {"path": str(outside / "secret.txt")})[0] is True
assert api.post("/api/settings", json={"sandbox_workspace": True}).get_json()[
    "sandbox_workspace"
] is True
assert precheck("readFile", {"path": str(outside / "secret.txt")})[0] is False
print("settings endpoint toggle ok")

print("\nSANDBOX TEST OK")
