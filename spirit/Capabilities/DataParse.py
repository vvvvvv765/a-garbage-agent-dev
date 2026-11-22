"""
parseData 能力：把 CSV / JSON / YAML / XML / SQLite 解析成模型能直接读的形状。

设计取舍：
  - 不整份回吐，先给结构（类型 / 键 / 行数 / 列名），再给有限预览
  - 大文件按 offset / limit 翻页；结果超长由内核统一 spill 落盘
  - SQLite 只读打开（mode=ro + query_only），只允许查询，不允许写
"""
import csv
import io
import json
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from .Files import human_size, resolve
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec

MAX_SOURCE = 32 * 1024 * 1024
MAX_SCAN_ROWS = 200000
DEFAULT_LIMIT = 30


def _decode(raw):
    for charset in ("utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(charset), charset
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _load_source(arguments):
    text = arguments.get("text")
    file_arg = str(arguments.get("file") or "").strip()
    if file_arg:
        path = resolve(arguments.get("__workdir"), file_arg)
        if not path.exists():
            raise ValueError(f"文件不存在：{path}")
        if path.is_dir():
            raise ValueError(f"这是文件夹：{path}")
        size = path.stat().st_size
        if size > MAX_SOURCE:
            raise ValueError(f"文件太大（{human_size(size)}，上限 {human_size(MAX_SOURCE)}）")
        raw = path.read_bytes()
        if b"\x00" in raw[:4096]:
            raise ValueError("看起来是二进制文件；SQLite 请用 format=sqlite")
        decoded, charset = _decode(raw)
        return decoded, str(path), path.suffix.lower(), charset
    if text is not None:
        return str(text), "（内联文本）", "", "utf-8"
    raise ValueError("file 和 text 至少要给一个")


def _detect(text, suffix):
    low = suffix.lower()
    if low in (".json",):
        return "json"
    if low in (".yaml", ".yml"):
        return "yaml"
    if low in (".xml",):
        return "xml"
    if low in (".csv", ".tsv"):
        return "csv"
    if low in (".db", ".sqlite", ".sqlite3"):
        return "sqlite"
    sample = text.lstrip()[:200]
    if sample.startswith("{") or sample.startswith("["):
        return "json"
    if sample.startswith("<"):
        return "xml"
    first = text.splitlines()[0] if text.splitlines() else ""
    if "," in first or "\t" in first or ";" in first:
        return "csv"
    if ":" in first and not first.strip().startswith(("http://", "https://")):
        return "yaml"
    return "csv"


def _clip(value, limit=120):
    text = str(value)
    text = text.replace("\r", " ").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, dict):
        return f"object({len(value)})"
    if isinstance(value, list):
        return f"array({len(value)})"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _preview(value, limit=3500):
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = repr(value)
    if len(text) > limit:
        text = text[:limit] + "\n…（预览已截断）"
    return text


def _walk(value, path):
    """支持 a.b[0].c / $[0].name 这样的简单路径。"""
    path = str(path or "").strip()
    if not path or path in ("$", "."):
        return value
    if path.startswith("$"):
        path = path[1:]
    token = ""
    index = 0
    parts = []
    while index < len(path):
        char = path[index]
        if char == ".":
            if token:
                parts.append(token)
                token = ""
            index += 1
        elif char == "[":
            if token:
                parts.append(token)
                token = ""
            end = path.find("]", index)
            if end < 0:
                raise ValueError(f"路径不合法：{path}")
            parts.append(int(path[index + 1:end]))
            index = end + 1
        else:
            token += char
            index += 1
    if token:
        parts.append(token)
    current = value
    for part in parts:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise KeyError(f"下标越界：{part}")
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise KeyError(f"键不存在：{part}")
            current = current[part]
    return current


def _describe(value, path="", limit=DEFAULT_LIMIT, offset=0):
    value = _walk(value, path)
    lines = []
    if isinstance(value, dict):
        keys = list(value.keys())
        lines.append(f"类型：对象 · 键 {len(keys)} 个")
        lines.append("键：" + ", ".join(str(key) for key in keys[:60])
                     + (" …" if len(keys) > 60 else ""))
        for key in keys[:limit]:
            item = value[key]
            lines.append(f"  {key}: {_type_name(item)} = {_clip(item)}")
        if len(keys) > limit:
            lines.append(f"…（还有 {len(keys) - limit} 个键）")
    elif isinstance(value, list):
        start = max(0, int(offset))
        end = start + max(1, int(limit))
        lines.append(f"类型：数组 · 长度 {len(value)}")
        for pos, item in enumerate(value[start:end], start=start):
            lines.append(f"  [{pos}] {_type_name(item)} = {_clip(item)}")
        if end < len(value):
            lines.append(f"…（还有 {len(value) - end} 项，可用 offset 继续）")
    else:
        lines.append(f"类型：{_type_name(value)}")
        lines.append(f"值：{_clip(value, 1000)}")
    lines.append("预览：")
    lines.append(_preview(value))
    return "\n".join(lines)


def _csv(text, delimiter="", limit=DEFAULT_LIMIT, offset=0):
    sample = text[:16384]
    if delimiter:
        rows_iter = csv.reader(io.StringIO(text), delimiter=str(delimiter)[0])
    else:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            rows_iter = csv.reader(io.StringIO(text), dialect=dialect)
        except csv.Error:
            rows_iter = csv.reader(io.StringIO(text))
    rows = []
    total = 0
    width = 0
    for row in rows_iter:
        total += 1
        if total > MAX_SCAN_ROWS:
            break
        width = max(width, len(row))
        rows.append(row)
    if not rows:
        return "CSV：空文件"
    header = rows[0]
    body = rows[1:]
    start = max(0, int(offset))
    end = start + max(1, int(limit))
    shown = body[start:end]
    lines = [
        f"CSV：{total - 1} 行数据 · {max(width, len(header))} 列"
        + (f"（扫描到 {MAX_SCAN_ROWS} 行后停止）" if total > MAX_SCAN_ROWS else ""),
        "列：" + " | ".join(_clip(item, 40) for item in header),
        "",
        " | ".join(_clip(item, 40) for item in header),
        " | ".join("---" for _ in header),
    ]
    for row in shown:
        padded = list(row) + [""] * (len(header) - len(row))
        lines.append(" | ".join(_clip(item, 60) for item in padded[:len(header)]))
    if end < len(body):
        lines.append(f"…（还有 {len(body) - end} 行，可用 offset 继续）")
    return "\n".join(lines)


def _xml(text, path="", limit=DEFAULT_LIMIT):
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        return f"XML 解析失败：{error}"
    if path:
        nodes = root.findall(path)
        if not nodes:
            return f"XML 路径没有匹配：{path}"
        lines = [f"XML 路径 {path}：{len(nodes)} 个节点"]
        for node in nodes[:limit]:
            lines.append(
                f"  <{node.tag}> attrs={dict(node.attrib)} text={_clip(node.text or '', 200)}"
            )
        return "\n".join(lines)
    lines = [f"根节点：<{root.tag}> 属性={dict(root.attrib)}"]

    def walk(node, depth):
        if depth > 8 or len(lines) > 500:
            return
        children = list(node)
        text = (node.text or "").strip()
        lines.append(
            "  " * depth + f"<{node.tag}>" + (f" {_clip(text, 100)}" if text else "")
        )
        for child in children[:50]:
            walk(child, depth + 1)

    for child in list(root)[:50]:
        walk(child, 1)
    if len(list(root)) > 50:
        lines.append(f"…（根节点还有 {len(list(root)) - 50} 个子节点）")
    return "\n".join(lines)


def _sqlite(path, query="", params=None, limit=DEFAULT_LIMIT):
    from urllib.parse import quote

    uri = "file:" + quote(str(Path(path).resolve()).replace("\\", "/"), safe="/:") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as error:
        return f"SQLite 打开失败：{error}"
    try:
        connection.execute("PRAGMA query_only=ON")
        if not query:
            cursor = connection.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            objects = cursor.fetchall()
            lines = [f"SQLite：{len(objects)} 个表 / 视图"]
            for name, kind in objects:
                quoted = str(name).replace('"', '""')
                cols = connection.execute(f'PRAGMA table_info("{quoted}")').fetchall()
                column_text = ", ".join(
                    f"{row[1]} {row[2]}" for row in cols
                )
                lines.append(f"  {name} ({kind})：{column_text}")
            return "\n".join(lines)

        head = query.lstrip().split(None, 1)[0].lower() if query.strip() else ""
        if head not in ("select", "with", "pragma", "explain"):
            return "SQLite：只允许查询（select / with / pragma / explain），不允许写"
        cursor = connection.execute(query, params or [])
        columns = [item[0] for item in (cursor.description or [])]
        rows = cursor.fetchmany(max(1, min(500, int(limit))) + 1)
        truncated = len(rows) > limit
        rows = rows[:limit]
        lines = [f"SQLite 查询：{len(rows)} 行" + ("（还有更多）" if truncated else "")]
        lines.append("列：" + " | ".join(str(item) for item in columns))
        for row in rows:
            lines.append(" | ".join(_clip(item, 80) for item in row))
        return "\n".join(lines)
    except sqlite3.Error as error:
        return f"SQLite 查询失败：{error}"
    finally:
        connection.close()


class DataParseCapability:
    name = "parseData"
    description = (
        "解析结构化数据：CSV / JSON / YAML / XML / SQLite。"
        "给 file 或 text；format=auto 按扩展名 / 内容判断。"
        "JSON / YAML 可用 path 取子结构（如 data.items[0].name）；"
        "SQLite 用 query 执行只读 SQL；大结果用 offset / limit 翻页。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "文件路径；相对路径按工作目录解析"},
            "text": {"type": "string", "description": "直接给一段文本（与 file 二选一）"},
            "format": {
                "type": "string",
                "enum": ["auto", "csv", "json", "yaml", "xml", "sqlite"],
                "description": "数据格式，默认 auto",
            },
            "path": {"type": "string", "description": "JSON / YAML 子路径，如 data.items[0]"},
            "query": {"type": "string", "description": "SQLite 查询（只读）"},
            "params": {"type": "array", "description": "SQLite 查询参数"},
            "delimiter": {"type": "string", "description": "CSV 分隔符，留空自动识别"},
            "offset": {"type": "integer", "description": "从第几行 / 项开始，默认 0"},
            "limit": {"type": "integer", "description": "最多显示多少行 / 项，默认 30"},
        },
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            trust="untrusted", side_effect="read", timeout=60, max_inline=6000,
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        file_arg = str(arguments.get("file") or "").strip()
        try:
            limit = min(200, max(1, int(arguments.get("limit", DEFAULT_LIMIT))))
            offset = max(0, int(arguments.get("offset", 0)))
        except (TypeError, ValueError):
            return "解析失败：offset / limit 必须是整数"
        fmt = str(arguments.get("format") or "auto").lower()
        if fmt == "auto" and file_arg.lower().endswith((".db", ".sqlite", ".sqlite3")):
            fmt = "sqlite"
        if fmt == "sqlite":
            if not file_arg:
                return "解析失败：sqlite 需要 file"
            try:
                path = resolve(self.__workdir, file_arg)
                if not path.exists():
                    return f"解析失败：文件不存在 {path}"
                return _sqlite(
                    str(path), str(arguments.get("query") or ""),
                    arguments.get("params"), limit,
                )
            except SandboxDenied:
                raise
            except Exception as error:
                return f"解析失败：{error}"
        try:
            text, label, suffix, charset = _load_source(
                {**arguments, "__workdir": self.__workdir}
            )
        except SandboxDenied:
            raise
        except Exception as error:
            return f"解析失败：{error}"
        if fmt == "auto":
            fmt = _detect(text, suffix)
        header = f"### {label}（{fmt}，{charset}，{human_size(len(text.encode('utf-8')))}）"
        try:
            if fmt == "json":
                value = json.loads(text)
                body = _describe(
                    value, str(arguments.get("path") or ""), limit, offset
                )
            elif fmt == "yaml":
                documents = list(yaml.safe_load_all(text))
                if len(documents) == 1:
                    value = documents[0]
                    body = _describe(
                        value, str(arguments.get("path") or ""), limit, offset
                    )
                else:
                    body = f"YAML：{len(documents)} 个文档\n" + _describe(
                        documents, str(arguments.get("path") or ""), limit, offset
                    )
            elif fmt == "csv":
                body = _csv(
                    text, str(arguments.get("delimiter") or ""), limit, offset
                )
            elif fmt == "xml":
                body = _xml(text, str(arguments.get("path") or ""), limit)
            else:
                return f"解析失败：不支持的格式 {fmt}"
        except json.JSONDecodeError as error:
            return f"JSON 解析失败：{error}"
        except yaml.YAMLError as error:
            return f"YAML 解析失败：{error}"
        except (KeyError, IndexError, ValueError) as error:
            return f"路径解析失败：{error}"
        return header + "\n" + body
