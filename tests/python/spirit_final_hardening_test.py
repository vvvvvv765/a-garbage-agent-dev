"""批 J：子进程环境白名单、日志轮转、审计失败策略、process pid 别名。"""
import os
import sys
import tempfile
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities.Sandbox import sandbox  # noqa: E402
from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
from Log import log  # noqa: E402
from Paths import log_dir  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-j-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-j-work-"))
engine = Engine(home=home, workdir=work)

# ---------- 1. 环境变量白名单 ----------
os.environ["MY_SECRET_TOKEN"] = "should-not-leak"
env = sandbox.bash_env(str(work))
assert "MY_SECRET_TOKEN" not in env, "白名单外的变量不该传"
assert env.get("PATH"), "PATH 必须保留（否则命令都跑不了）"
assert Path(env["HOME"]) == work.resolve()
assert Path(env["TEMP"]) == (work / "tmp").resolve()
assert env.get("SPIRIT_SANDBOX") == "workspace"

out = capabilities.run([CapabilityInput(
    "e1", "bash", "{}",
    {"command": 'echo "home=$HOME"; python -c "print(1+1)"'},
)])[0]
assert work.name in out.content, out.content   # bash 里 HOME 是 msys 路径
assert "2" in out.content, out.content
out = capabilities.run([CapabilityInput(
    "e2", "bash", "{}", {"command": "echo ${MY_SECRET_TOKEN:-unset}"},
)])[0]
assert "unset" in out.content, out.content
print("1. 环境白名单 ok")

# 用户显式允许的变量可以传
config.set("engine.sandbox.env_allow", ["MY_SECRET_TOKEN"])
sandbox.reload()
env = sandbox.bash_env(str(work))
assert env.get("MY_SECRET_TOKEN") == "should-not-leak"
config.set("engine.sandbox.env_allow", [])
sandbox.reload()
print("1b. env_allow ok")

# ---------- 2. 日志轮转 ----------
config.set("engine.log_max_bytes", 64 * 1024)
config.set("engine.log_backups", 2)
log.rebind()
for index in range(1500):
    log.info("Test", f"line {index} " + "x" * 80)
time.sleep(0.2)
directory = Path(log_dir())
assert (directory / "spirit.log").exists()
rotated = list(directory.glob("spirit.log.*"))
assert rotated, "超过上限应该轮转"
print("2. 日志轮转 ok")

# ---------- 3. 审计失败：高风险不再静默放行 ----------
config.set("engine.approval", "auto")
blocked = Path(tempfile.mkdtemp(prefix="spirit-j-block-")) / "not-a-dir"
blocked.write_text("x", encoding="utf-8")          # 把"日志目录"占成一个文件
os.environ["SPIRIT_LOG_DIR"] = str(blocked)
security.set_approver(None)
allowed_first, _ = security.check("writeFile", "{}")
allowed_second, reason = security.check("writeFile", "{}")
assert allowed_second is False and "审计不可用" in reason, (allowed_second, reason)
asked = []
security.set_approver(lambda request: asked.append(request) or False)
allowed_third, reason = security.check("writeFile", "{}")
assert allowed_third is False and asked and asked[-1].get("audit_broken"), (allowed_third, asked)
os.environ.pop("SPIRIT_LOG_DIR", None)
security.set_approver(None)
security.check("readFile", "{}")                  # 写一次成功 → 复位
assert security.audit_broken is False
print("3. 审计失败策略 ok")

# ---------- 4. processOutput / kill 接受 pid 别名 ----------
schemas = {schema["name"]: schema for schema in capabilities.schemas()}
for name in ("processOutput", "processKill"):
    props = schemas[name]["parameters"]["properties"]
    assert "id" in props and "pid" in props, (name, props)
out = capabilities.run([CapabilityInput("p1", "processOutput", "{}", {})])[0]
assert "需要 id" in out.content, out.content
print("4. pid 别名 ok")

print("ALL FINAL HARDENING TESTS PASSED")
