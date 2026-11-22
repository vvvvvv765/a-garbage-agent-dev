"""桌面壳默认值：不设人为步数上限、不默认把文件能力锁在工作区。"""
import re
from pathlib import Path

root = Path(os.environ.get("SPIRIT_DESKTOP") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "desktop"))
defaults = (root / "src" / "defaults.ts").read_text(encoding="utf-8")
main = (root / "src" / "main.ts").read_text(encoding="utf-8")

assert re.search(r"max_steps:\s*0\b", defaults), "max_steps 默认应为 0（不限）"
assert re.search(r"workspace_only:\s*false\b", defaults), "workspace_only 默认应为 false"
assert re.search(r"reasoning:\s*'high'", defaults), "思考档位默认应为 DeepSeek 的 high"
assert "max_steps_migrated" in main, "旧 max_steps=8 的迁移逻辑不见了"
assert "sandbox_workspace_migrated" in main, "旧 workspace_only=true 的迁移逻辑不见了"
print("desktop defaults ok")
print("\nDESKTOP DEFAULTS TEST OK")
