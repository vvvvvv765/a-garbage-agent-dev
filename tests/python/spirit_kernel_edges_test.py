"""内核依赖边：主体系之间不许新增控制耦合（数据表读取例外）。

规则来自 2026-11-19 的边界讨论：
  - 内存 / 硬盘是共享资源，允许被读
  - CPU / GPU / Render / Memory / Disk 不许 import 对方来做控制
  - 具体能力插件另由 spirit_kernel_boundary_test 守
"""
import ast
from pathlib import Path

root = Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

FORBIDDEN = {
    "DC": {"GPU", "Render", "Disk", "Engine", "WebUI", "Prompts"},
    "GPU": {"DC", "Capabilities", "Disk", "Render", "Engine", "WebUI", "Prompts"},
    "Memory": {"DC", "GPU", "Capabilities", "Disk", "Render", "Engine", "WebUI", "Prompts"},
    "Disk": {"DC", "GPU", "Capabilities", "Memory", "Render", "Engine", "WebUI", "Prompts"},
    "Render": {"DC", "GPU", "Capabilities", "Disk", "Engine", "WebUI", "Prompts"},
}


def imports_of(package):
    found = set()
    for path in (root / package).glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if node.module:
                    found.add(node.module.split(".")[0])
    return found


bad = []
for package, forbidden in FORBIDDEN.items():
    hits = sorted(imports_of(package) & forbidden)
    for name in hits:
        bad.append(f"{package} -> {name}")

assert not bad, "内核主体系出现新的控制耦合：\n" + "\n".join(bad)
print("1. 主体系依赖边 ok:", ", ".join(sorted(FORBIDDEN)))
print("\nKERNEL EDGES TEST PASSED")
