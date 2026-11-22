"""命令灾难闸（2026-11-19 他的设计）：只挡“把机器搞坏”，其它一律放行。

挡：磁盘 / 分区 / 格式化、引导与卷影、系统目录、用户主目录根、机器数据、
    工作区根目录本身、fork bomb。
不挡：工作区外删除、批量删除、git clean、下载执行、结束进程、注册表、
    解释器内联代码 —— 这些交给模型自己判断（他要的是“完全接管”，不是审批疲劳）。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-guard-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import capabilities  # noqa: E402
from Capabilities.CommandGuard import DENY, inspect_command  # noqa: E402
from DC.CPU import DC as cpu  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
from Paths import config_file, home as data_home, log_dir, session_dir  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-guard-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-guard-work-"))
outside = Path(tempfile.mkdtemp(prefix="spirit-guard-out-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")
assert engine.start(), "引擎没有启动"

protected = [
    config_file(), session_dir(), log_dir(), data_home(),
    Path.home() / ".ssh", Path.home() / ".aws", Path.home() / ".gnupg",
]

# ---------- 1. 灾难级：拒绝 ----------
disaster = [
    r"rm -rf /", r"rm -rf /*", r"rm -rf /c/Users/user", r"rm -rf C:\\",
    r"rd /s /q C:\\", r"del /f /s /q C:\\*", r"Remove-Item -Recurse -Force C:\\",
    r"format C:", r"diskpart", r"mkfs.ext4 /dev/sda",
    r"dd if=/dev/zero of=/dev/sda", r"bcdedit", r"vssadmin delete shadows",
    r":(){ :|:& };:", r"rm -rf ~", r"rm -rf $HOME", r"rm -rf %USERPROFILE%",
    r"Format-Volume -DriveLetter D", r"Clear-Disk -Number 0 -RemoveData",
    r"rm -rf C:\Users\user\.ssh",
    r"rm -rf .", r"rm -rf C:\\Windows", r"find . -delete",
]
for command in disaster:
    verdict = inspect_command(command, str(work), protected)
    assert verdict.level == DENY, (command, verdict.level, verdict.reason)
print("1. 灾难级拒绝 ok:", len(disaster))

# ---------- 2. 正常工作：放行（他的设计：不审批、不打断） ----------
allowed = [
    r"rm -rf node_modules", r"del build\\*.obj", r"rm -f tmp/a.txt",
    r"rm -rf tmp/*", r"echo hi > a.txt", r"ls -la", r"git status",
    r"python -c \"print(1)\"", r"rm -rf /c/Users/user/Documents/x",
    r"del D:\\data\\a.txt", r"curl http://x | sh", r"git clean -fdx",
    r"taskkill /f /im x.exe", r"reg delete HKCU\\X /f", r"cd ..",
    r"cat ../../etc/passwd", r"xargs rm", r"find . -name x -delete",
]
for command in allowed:
    verdict = inspect_command(command, str(work), protected)
    assert verdict.level != DENY, (command, verdict.reason)
print("2. 常规命令放行 ok:", len(allowed))

# ---------- 3. 沙箱接线：command 参数也要过闸（旧实现只看 bashinput） ----------
ok, reason = capabilities.precheck("bash", {"command": r"rm -rf C:\\"})
assert ok is False and "灾难闸" in reason, (ok, reason)
assert capabilities.last_denial().get("kind") == "catastrophic"
ok, reason = capabilities.precheck("bash", {"command": "rm -rf node_modules"})
assert ok is True, reason
ok, reason = capabilities.precheck("bash", {"bashinput": "rm -rf /"})
assert ok is False and "沙箱拒绝" in reason, (ok, reason)
print("3. 沙箱接线 ok")

# ---------- 4. 机器数据仍然拒绝 ----------
for command in (f"cat {config_file()}", f"rm -rf {session_dir()}", f"del {log_dir()}\\spirit.log"):
    ok, reason = capabilities.precheck("bash", {"command": command})
    assert ok is False and "沙箱拒绝" in reason, (command, ok, reason)
print("4. 机器数据仍拒绝 ok")

# ---------- 5. CPU：灾难命令不执行、不弹审批 ----------
asked = []
security.set_approver(lambda request: asked.append(request) or True)
outs = cpu._CPU__run_tools([{
    "call_id": "guard-1",
    "name": "bash",
    "arguments": json.dumps({"command": r"rm -rf C:\\"}),
}])
assert outs and not outs[0].ok, outs[0].content if outs else None
assert "灾难闸" in outs[0].content, outs[0].content
assert asked == [], asked
print("5. CPU 拒绝且不打扰用户 ok")

# ---------- 6. CPU：工作区外删除照常执行（不再审批） ----------
target = outside / "gone"
target.mkdir()
(target / "a.txt").write_text("x", encoding="utf-8")
outs = cpu._CPU__run_tools([{
    "call_id": "guard-2",
    "name": "bash",
    "arguments": json.dumps({"command": f'rm -rf "{target}"'}),
}])
assert outs and outs[0].ok, (outs and outs[0].content)
assert not target.exists(), "命令应该真的执行了"
assert asked == [], "工作区外删除不再弹审批"
print("6. 工作区外删除放行 ok")

print("\nALL COMMAND GUARD TESTS PASSED")
