"""工具契约的"模型可用性"：参数名、描述指引、兼容旧参数。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-tc-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-tc-work-"))
engine = Engine(home=home, workdir=work)

schemas = {schema["name"]: schema for schema in capabilities.schemas()}
assert len(schemas) >= 16, len(schemas)

# ---------- 1. bash：推荐 command，兼容 bashinput ----------
bash = schemas["bash"]
props = bash["parameters"]["properties"]
assert "command" in props and "bashinput" in props, props
assert "command" in bash["parameters"].get("required", []) or not bash["parameters"].get("required"), bash
assert "优先用 readFile" in bash["description"], bash["description"]

def run(arguments):
    return capabilities.run([CapabilityInput("c", "bash", "{}", arguments)])[0]

assert "hi" in run({"command": "echo hi"}).content
assert "hi" in run({"bashinput": "echo hi"}).content   # 旧名兼容
overload = run({})
assert "command 不能为空" in overload.content, overload.content
print("1. bash 契约 ok")

# ---------- 2. 文件工具的描述带"先看再改" ----------
assert "先读" in schemas["readFile"]["description"] or "读一遍" in schemas["readFile"]["description"]
assert "replaceInFile" in schemas["writeFile"]["description"]
assert "全角" in schemas["replaceInFile"]["description"]
assert "findFiles" in schemas["searchFiles"]["description"]
print("2. 文件工具描述 ok")

# ---------- 3. 替换失败给出可执行的下一步 ----------
target = work / "a.txt"
target.write_text("hello\nworld\n", encoding="utf-8")
out = capabilities.run([CapabilityInput(
    "r", "replaceInFile", "{}",
    {"path": "a.txt", "old_text": "你好世界", "new_text": "x"},
)])[0]
assert "原文没有找到" in out.content and "全角" in out.content, out.content

# 只差行尾空格 / CRLF 时走宽松匹配，并明确告诉模型是宽松匹配
target.write_text("hello\nworld\n", encoding="utf-8")
out = capabilities.run([CapabilityInput(
    "r2", "replaceInFile", "{}",
    {"path": "a.txt", "old_text": "hello ", "new_text": "x"},
)])[0]
assert out.ok and "宽松匹配" in out.content, out.content
assert target.read_text(encoding="utf-8") == "x\nworld\n", target.read_text(encoding="utf-8")
print("3. 替换失败指引 / 宽松匹配 ok")

print("ALL TOOL CONTRACT TESTS PASSED")
