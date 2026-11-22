"""内核边界（K1）：具体能力是插件，不许直接碰内存 / 总线 / 调度等内核体系。

允许：stdlib、Config / Log / Paths / Faults / Cancel / Turn / Usage / Redact，
以及 Capabilities 包内部的相对 import（框架零件）。
禁止：Memory / Bus / DC / Engine / GPU / Render / Disk / Scenarios / WebUI / Provider 等。
"""
import ast
import importlib.util
import sys
from pathlib import Path

root = Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
sys.path.insert(0, str(root))

from Capabilities.System import BUILTIN  # noqa: E402

FORBIDDEN = {
    "Memory", "Bus", "DC", "Engine", "GPU", "Render", "Disk",
    "Scenarios", "WebUI", "Provider", "MoBo", "AgentStart",
    "UserInput", "Contract",
}


def module_file(module):
    name = module.split(".")[-1]
    return root / "Capabilities" / f"{name}.py"


def top_level_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:      # 包内相对 import（.Spec / .Files…）：允许
                continue
            if node.module:
                found.add(node.module.split(".")[0])
    return found


bad = []
checked = set()
for entry in BUILTIN:
    module = entry["module"]
    if module in checked:
        continue
    checked.add(module)
    path = module_file(module)
    assert path.exists(), path
    for name in sorted(top_level_imports(path) & FORBIDDEN):
        bad.append(f"{path.name}: {name}")

assert not bad, "插件直接 import 了内核体系：\n" + "\n".join(bad)
print(f"1. {len(checked)} 个能力插件不碰内核 ok")

# 框架自己可以 import 内核（System 负责写表 / 落盘），但插件不行
framework = top_level_imports(root / "Capabilities" / "System.py")
assert "Memory" in framework and "Disk" in framework
print("2. 能力框架保留内核注入 ok")

# Todo 走注入的 store
todo_source = (root / "Capabilities" / "Todo.py").read_text(encoding="utf-8")
assert "Memory" not in todo_source and "todo" in todo_source
print("3. todo 改注入 ok")

print("\nKERNEL BOUNDARY TEST PASSED")
