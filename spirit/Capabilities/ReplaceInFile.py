"""
replaceInFile 能力：精确字符串替换（改代码的刚需，比 sed 稳）。
"""
from .Files import MAX_SEARCH_BYTES, resolve, write_atomic
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec


def _exact_ranges(text, old):
    ranges = []
    start = 0
    while True:
        index = text.find(old, start)
        if index < 0:
            return ranges
        ranges.append((index, index + len(old)))
        start = index + len(old)


def _loose_ranges(text, old):
    """逐行比对，忽略行尾空格和 CRLF；用于精确匹配失败后的兜底。"""
    old_lines = [line.rstrip() for line in old.splitlines()]
    if not old_lines:
        return []
    lines = text.splitlines(keepends=True)
    offsets = []
    position = 0
    for line in lines:
        offsets.append((position, position + len(line)))
        position += len(line)
    ranges = []
    for index in range(len(lines) - len(old_lines) + 1):
        window = lines[index:index + len(old_lines)]
        if all(
            window[offset].rstrip("\r\n").rstrip() == old_lines[offset]
            for offset in range(len(old_lines))
        ):
            start = offsets[index][0]
            end = offsets[index + len(old_lines) - 1][1]
            if not old.endswith(("\n", "\r")):
                while end > start and text[end - 1] in "\r\n":
                    end -= 1
            ranges.append((start, end))
    return ranges


class ReplaceInFileCapability:
    name = "replaceInFile"
    description = (
        "把文件里的一段原文精确替换成新文本。"
        "occurrence 指定替换第几处（默认 1）；传 0 表示全部替换。"
        "原文对不上会失败（注意空格/换行/全角半角），先用 readFile 确认要替换的片段。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径；相对路径按工作目录解析"},
            "old_text": {"type": "string", "description": "要被替换的原文（必须逐字一致）"},
            "new_text": {"type": "string", "description": "替换成的新文本；空串表示删除"},
            "occurrence": {
                "type": "integer",
                "description": "替换第几处（1 开始）；0 = 全部替换；默认 1",
            },
        },
        "required": ["path", "old_text", "new_text"],
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
            if not path.exists():
                return f"文件不存在：{path}"
            if path.is_dir():
                return f"这是文件夹，不是文件：{path}"
            if path.stat().st_size > MAX_SEARCH_BYTES:
                return f"文件太大（{path.stat().st_size} 字节，上限 {MAX_SEARCH_BYTES}），改不了"
            old = arguments["old_text"]
            new = arguments["new_text"]
            if not old:
                return "old_text 不能为空"
            # 用 bytes 解码保留 CRLF（read_text 会把行尾统一成 \n，写回时丢格式）
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return "文件不是 UTF-8 文本，改不了（二进制或别的编码）"
        except SandboxDenied:
            raise
        except Exception as error:
            return f"读取失败：{error}"

        ranges = _exact_ranges(text, old)
        loose = False
        if not ranges:
            ranges = _loose_ranges(text, old)
            loose = bool(ranges)
        total = len(ranges)
        if total == 0:
            return (
                "原文没有找到（逐字和忽略行尾空格/CRLF 的比对都失败）；"
                "先用 readFile 确认片段——注意空格、换行、全角/半角"
            )

        occurrence = int(arguments.get("occurrence", 1))
        if occurrence < 0:
            return "occurrence 不能是负数：1 = 第 1 处，0 = 全部"

        newline = "\r\n" if "\r\n" in text else "\n"
        replacement = new.replace("\r\n", "\n")
        if newline != "\n":
            replacement = replacement.replace("\n", newline)

        if occurrence == 0:
            updated = text
            for start, end in reversed(ranges):
                updated = updated[:start] + replacement + updated[end:]
            replaced = total
        else:
            if occurrence > total:
                return f"原文只出现 {total} 次，没有第 {occurrence} 处"
            start, end = ranges[occurrence - 1]
            updated = text[:start] + replacement + text[end:]
            replaced = 1

        try:
            write_atomic(path, updated)
        except Exception as error:
            return f"写入失败：{error}"

        note = "（宽松匹配：忽略了行尾空格/CRLF 差异）" if loose else ""
        if occurrence == 0:
            return f"已替换全部 {replaced} 处{note}：{path}"
        return f"已替换第 {occurrence} 处（该片段在文件中出现 {total} 次）{note}：{path}"
