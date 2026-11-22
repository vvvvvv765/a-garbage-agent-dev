"""
writeFile 能力：整份写入（新建或覆盖）。改局部请用 replaceInFile。
"""
from .Files import human_size, resolve, write_text
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec


class WriteFileCapability:
    name = "writeFile"
    description = (
        "把一个文件整份写入（不存在就新建，存在就覆盖）。"
        "只想改局部时用 replaceInFile，别整份重写；覆盖前先 readFile 确认现有内容。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径；相对路径按工作目录解析"},
            "content": {"type": "string", "description": "完整内容（UTF-8 文本）"},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self):
        self.__workdir = None

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",)
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        try:
            path = resolve(self.__workdir, arguments["path"])
            if path.is_dir():
                return f"这是文件夹，不能写入：{path}"
            existed = path.exists()
            size = write_text(path, arguments.get("content", ""))
        except SandboxDenied:
            raise
        except Exception as error:
            return f"写入失败：{error}"
        action = "覆盖" if existed else "新建"
        return f"已{action}：{path}（{human_size(size)}）"
