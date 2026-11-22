"""
findFiles 能力：按文件名找文件（子串或通配符）。
"""
from .Executions import executions
from .Files import match_name, walk_files
from .Spec import CapabilitySpec


class FindFilesCapability:
    name = "findFiles"
    description = (
        "按文件名找文件：name 可以是子串（如 config），也可以是通配符（如 *.py）。"
        "会自动跳过 .git / .venv / node_modules 等。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "文件名子串或通配符"},
            "path": {"type": "string", "description": "从哪个文件夹开始找，默认工作目录"},
            "max_results": {"type": "integer", "description": "最多返回多少条，默认 100"},
        },
        "required": ["name"],
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
        pattern = arguments["name"]
        limit = int(arguments.get("max_results", 100))
        hits = []
        for full, rel in walk_files(self.__workdir, arguments.get("path", ".")):
            executions.check()
            if match_name(full.name, pattern):
                hits.append(rel)
                if len(hits) >= limit:
                    break
        if not hits:
            return f"没有找到匹配「{pattern}」的文件"
        result = "\n".join(hits)
        if len(hits) >= limit:
            result += f"\n…（达到上限 {limit} 条，可调 max_results）"
        return result
