"""
searchFiles 能力：在文件内容里搜（文本或正则）。

用 regex 模块的 timeout：灾难性回溯（ReDoS）不会把线程永久占住。
"""
import regex

from .Executions import executions
from .Files import MAX_SEARCH_BYTES, is_binary, match_name, walk_files
from .Spec import CapabilitySpec


class SearchFilesCapability:
    name = "searchFiles"
    description = (
        "在文件内容里搜文本或正则，返回「路径:行号: 内容」。"
        "pattern 是正则（特殊字符要转义）；按文件名找用 findFiles。"
        "可用 glob 只搜某类文件（如 *.py）；会自动跳过 .git / .venv / node_modules 等。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "要搜的文本或正则表达式"},
            "path": {"type": "string", "description": "从哪个文件夹开始搜，默认工作目录"},
            "glob": {"type": "string", "description": "文件名过滤，如 *.py；不填搜所有文本文件"},
            "max_results": {"type": "integer", "description": "最多返回多少条，默认 100"},
        },
        "required": ["pattern"],
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
            pattern = regex.compile(arguments["pattern"])
        except regex.error as error:
            return f"正则不合法：{error}"

        limit = int(arguments.get("max_results", 100))
        glob = arguments.get("glob")

        hits = []
        scanned = 0
        for full, rel in walk_files(self.__workdir, arguments.get("path", ".")):
            executions.check()
            if len(hits) >= limit:
                break
            if glob and not match_name(full.name, glob):
                continue
            try:
                if full.stat().st_size > MAX_SEARCH_BYTES or is_binary(full):
                    continue
                text = full.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            for number, line in enumerate(text.splitlines(), 1):
                executions.check()
                try:
                    matched = pattern.search(line, timeout=0.05)
                except TimeoutError:
                    return (
                        "正则匹配超时（可能是灾难性回溯，例如 (a+)+$）；"
                        f"卡在 {rel} 第 {number} 行。换一个更收敛的表达式再试"
                    )
                if matched:
                    snippet = line.strip()
                    if len(snippet) > 200:
                        snippet = snippet[:200] + "…"
                    hits.append(f"{rel}:{number}: {snippet}")
                    if len(hits) >= limit:
                        break

        if not hits:
            return f"没有匹配（扫了 {scanned} 个文件）"
        result = "\n".join(hits)
        if len(hits) >= limit:
            result += f"\n…（达到上限 {limit} 条，可调 max_results）"
        return result
