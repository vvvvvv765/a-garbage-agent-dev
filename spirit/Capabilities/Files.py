"""
能力共用的文件零件（不是能力，是能力体系内部的公共工具）

约定：
  - 相对路径按 workdir 解析；绝对路径原样用
  - 文本一律 UTF-8；读的时候坏字节用替换字符
  - 大文件不整读：超过上限截断并说明
  - 明显是二进制的文件（前 4KB 有 NUL）直接拒绝
"""
import fnmatch
import os
import uuid
from pathlib import Path

MAX_READ_BYTES = 512 * 1024
MAX_WRITE_BYTES = 1024 * 1024
MAX_SEARCH_BYTES = 2 * 1024 * 1024

# 搜索时跳过的重目录（不跳会和 .venv / node_modules 同归于尽）
SKIP_DIRS = {
    ".git", ".venv", "node_modules", "__pycache__",
    "shell", "Session_Storage", "Logs", ".idea",
}


def resolve(workdir, path):
    """把模型给的路径落成真实路径；边界交给沙箱。"""
    from .Sandbox import sandbox
    return sandbox.resolve(workdir, path)


def is_binary(path):
    try:
        with open(path, "rb") as file:
            return b"\x00" in file.read(4096)
    except OSError:
        return False


def read_text(path, offset=0, limit=2000):
    """按行读：返回 (lines, total_lines, truncated)。

    只读到 MAX_READ_BYTES 为止（分块读），不再整文件读进内存。
    """
    data = b""
    with open(path, "rb") as file:
        while len(data) < MAX_READ_BYTES:
            chunk = file.read(min(64 * 1024, MAX_READ_BYTES - len(data)))
            if not chunk:
                break
            data += chunk
    try:
        clipped = path.stat().st_size > len(data)
    except OSError:
        clipped = len(data) >= MAX_READ_BYTES
    if b"\x00" in data[:4096]:
        raise ValueError("看起来是二进制文件")
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    start = max(0, int(offset))
    end = start + max(1, int(limit))
    return lines[start:end], total, clipped or end < total


def write_atomic(path, content):
    """同目录临时文件 + os.replace：写到一半崩了也不会留下截断的文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        # newline=""：Windows 上不要做 LF→CRLF 翻译（`.sh` / Makefile 会被写坏）
        temp.write_text(content, encoding="utf-8", newline="")
        os.replace(temp, path)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def write_text(path, content):
    data = content.encode("utf-8")
    if len(data) > MAX_WRITE_BYTES:
        raise ValueError(f"内容太大（{len(data)} 字节，上限 {MAX_WRITE_BYTES}）")
    write_atomic(path, content)
    return len(data)


def human_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


def walk_files(workdir, path="."):
    """遍历目录（跳过 SKIP_DIRS / 沙箱保护的文件），产出 (Path, 相对路径)。"""
    from .Sandbox import sandbox

    root = resolve(workdir, path)
    if root.is_file():
        if sandbox.within(root, workdir):
            yield root, root.name
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and sandbox.within(Path(base) / d, workdir)
        ]
        for name in files:
            full = Path(base) / name
            if not sandbox.within(full, workdir):
                continue
            try:
                rel = str(full.relative_to(root))
            except ValueError:
                rel = str(full)
            yield full, rel


def match_name(name, pattern):
    """文件名匹配：带通配符按 glob，否则按子串（不区分大小写）。"""
    if "*" in pattern or "?" in pattern or "[" in pattern:
        return fnmatch.fnmatch(name.lower(), pattern.lower())
    return pattern.lower() in name.lower()
