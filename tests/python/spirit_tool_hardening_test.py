"""工具质量：bash 超时参数/失败标记、replace 宽松匹配、spill 头尾预览。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-toolq-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-toolq-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from Render import render  # noqa: E402

render.set_console(False)
engine = Engine(home=home, workdir=work)
engine.start()


def run(name, arguments):
    raw = json.dumps(arguments)
    return capabilities.run([CapabilityInput("c", name, raw, arguments)])[0]


# 1. bash timeout 参数生效（1 秒等不完 3 秒）
result = run("bash", {"command": "sleep 3", "timeout": 1})
assert "超时" in result.content and "timeout 参数" in result.content, result.content
print("1. bash timeout parameter ok")

# 2. 浏览器超时给出 GUI 提示
result = run("bash", {"command": "echo msedge; sleep 3", "timeout": 1})
assert "--headless" in result.content, result.content
print("2. GUI timeout hint ok")

# 3. replaceInFile 宽松匹配：行尾空格 + CRLF
target = work / "loose.txt"
target.write_bytes("alpha   \r\nbeta\r\ngamma\r\n".encode("utf-8"))
result = run("replaceInFile", {
    "path": "loose.txt", "old_text": "alpha\nbeta", "new_text": "X",
})
assert result.ok and "宽松匹配" in result.content, result.content
assert target.read_bytes() == "X\r\ngamma\r\n".encode("utf-8"), target.read_bytes()
print("3. replace loose match ok")

# 4. 失败统一带 “失败：” 前缀
result = run("does_not_exist", {})
assert not result.ok and result.content.startswith("失败："), result.content
print("4. unified failure marker ok")

# 5. 超过 inline 阈值落盘，预览包含头 + 尾
big = "HEAD-" + ("x" * 20000) + "-TAIL"
result = run("bash", {"command": f"printf %s '{big}'"})
assert "已落盘" in result.content, result.content[:200]
assert "HEAD-" in result.content and "-TAIL" in result.content, result.content[:200]
assert len(result.content) < 4000, len(result.content)
print("5. spill head+tail preview ok")

render.shutdown()
print("\nTOOL HARDENING TEST OK")
