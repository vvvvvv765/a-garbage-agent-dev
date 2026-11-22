"""
readFile 能力：读一个文本文件（可按行分段）。
"""
from .Files import read_text, resolve
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec


class ReadFileCapability:
    name = "readFile"
    description = (
        "读取一个文本文件，返回带行号的内容和总行数；改文件前先读一遍。"
        "大文件用 offset/limit 分段读（offset 从 0 开始）；"
        "不要在没读之前直接 writeFile 覆盖。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径；相对路径按工作目录解析"},
            "offset": {"type": "integer", "description": "从第几行开始（0 开始），默认 0"},
            "limit": {"type": "integer", "description": "最多读多少行，默认 2000"},
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self):
        self.__workdir = None

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            trust="untrusted", side_effect="read",
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        try:
            path = resolve(self.__workdir, arguments["path"])
            if not path.exists():
                return f"文件不存在：{path}"
            if path.is_dir():
                return f"这是文件夹，不是文件：{path}（用 listDir 看内容）"
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                return f"这是图片：{path}。用 viewImage 把它作为图像交给模型看。"
            lines, total, truncated = read_text(
                path,
                arguments.get("offset", 0),
                arguments.get("limit", 2000),
            )
        except SandboxDenied:
            raise
        except Exception as error:
            return f"读取失败：{error}"

        start = int(arguments.get("offset", 0)) + 1
        header = f"# {path}（共 {total} 行）"
        body = "\n".join(f"{start + i:>5}  {line}" for i, line in enumerate(lines))
        if truncated:
            body += f"\n…（只显示到第 {start + len(lines) - 1} 行；可调 offset/limit 继续读）"
        return f"{header}\n{body}"
