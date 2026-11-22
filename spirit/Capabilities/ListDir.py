"""
listDir 能力：列一个文件夹的直接内容（不递归）。
"""
from .Files import human_size, resolve
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec


class ListDirCapability:
    name = "listDir"
    description = "列出一个文件夹的直接内容（不递归）。文件夹在前，文件带大小。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件夹路径，默认当前工作目录"},
        },
        "additionalProperties": False,
    }

    def __init__(self):
        self.__workdir = None

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            side_effect="read",
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        try:
            path = resolve(self.__workdir, arguments.get("path", "."))
            if not path.exists():
                return f"文件夹不存在：{path}"
            if not path.is_dir():
                return f"这是文件，不是文件夹：{path}（用 readFile 读）"
            entries = sorted(
                path.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
            if not entries:
                return f"# {path}\n（空文件夹）"
            lines = [f"# {path}"]
            for entry in entries[:500]:
                try:
                    if entry.is_dir():
                        lines.append(f"d  {entry.name}/")
                    else:
                        lines.append(f"f  {entry.name}  ({human_size(entry.stat().st_size)})")
                except OSError:
                    lines.append(f"?  {entry.name}")
            if len(entries) > 500:
                lines.append(f"…（共 {len(entries)} 项，只列前 500）")
            return "\n".join(lines)
        except SandboxDenied:
            raise
        except Exception as error:
            return f"列出失败：{error}"
