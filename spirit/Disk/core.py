"""
硬盘体系（agent 计算机的存储主体系）

分工：
  - 内存：当前轮次要紧的数据（要给 GPU 加工、给大模型看）
  - 硬盘：冷数据——会话、工作区、**能力体系的落盘产物**、日志、沙箱目录。
    模型用能力（readFile / listDir / searchFiles）按需读取，不默认进上下文。

区域所有权（2026-11-20 拍板）：
  - `workspace`：作业文件（模型读写、bash cwd、交付物）——框架产物不写这里
  - `artifacts`：能力体系的落盘产物（大输出 spill / 下载的大文件 / 能力产物），
    框架托管、可整体清理；模型按 `meta.path` 读
  - `sessions` / `logs`：框架自身数据，能力不可读（受保护）
  - `sandbox`：隔离执行临时区；`uploads`：用户上传

它是主体系之一，**不可删除**：没有注销入口，开机必须存在。
工作区是它的子体系（`workspace` 区域），不是另一个独立的东西。
"""
import os
import re
import time
from pathlib import Path

from Config import config
from Paths import artifacts_dir, home, log_dir, session_dir

AREAS = ("workspace", "artifacts", "sessions", "logs", "sandbox", "uploads", "projects")

_SAFE = re.compile(r"[^0-9A-Za-z._-]+")


def _safe(text, limit=48):
    return _SAFE.sub("_", str(text or "").strip())[:limit].strip("._-") or "item"


class Disk:
    """存储主体系：给每个区域一个明确的根，能力只认区域，不直接拼路径。"""

    def __init__(self):
        pass

    # ---------- 区域 ----------
    def workspace(self):
        value = str(config.get("engine.workdir", "") or "").strip()
        root = Path(value).expanduser() if value else (home() / "workspace")
        return root.resolve()

    def roots(self):
        workspace = self.workspace()
        return {
            "workspace": workspace,
            "artifacts": artifacts_dir().resolve(),   # 框架产物区：不在工作区里
            "sessions": Path(session_dir()).resolve(),
            "logs": Path(log_dir()).resolve(),
            "sandbox": (home() / "Sandbox").resolve(),
            "uploads": (home() / "uploads").resolve(),
            "projects": (home() / "Projects").resolve(),
        }

    def area(self, name):
        name = str(name or "").strip()
        if name not in AREAS:
            raise ValueError(f"未知硬盘区域：{name}")
        path = self.roots()[name]
        if name in {"workspace", "artifacts", "sandbox", "uploads", "projects"}:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure(self):
        for name in AREAS:
            try:
                self.area(name)
            except OSError:
                continue

    # ---------- 落盘 ----------
    def artifact(self, name, data, suffix=".txt", folder="spill"):
        """把大结果写进硬盘，返回路径 / 大小 / 行数（不返回全文）。"""
        directory = self.area("artifacts")
        folder = _safe(folder or "spill")
        if folder:
            directory = directory / folder
        directory.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            raw = data
        else:
            raw = str(data or "").encode("utf-8")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = _safe(name or "output")
        candidate = directory / f"{stamp}-{base}{suffix}"
        index = 1
        while candidate.exists():
            candidate = directory / f"{stamp}-{base}-{index}{suffix}"
            index += 1
        candidate.write_bytes(raw)
        return {
            "path": str(candidate),
            "bytes": len(raw),
            "lines": raw.count(b"\n") + 1,
        }

    # ---------- 使用量 / 列出 ----------
    def usage(self, max_files=20000):
        result = {}
        for name in AREAS:
            path = self.roots()[name]
            item = {
                "name": name,
                "path": str(path),
                "exists": path.exists(),
                "bytes": 0,
                "files": 0,
                "truncated": False,
            }
            if path.exists():
                stack = [path]
                while stack and item["files"] < max_files:
                    current = stack.pop()
                    try:
                        entries = list(os.scandir(current))
                    except OSError:
                        continue
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir():
                                stack.append(Path(entry.path))
                            elif entry.is_file():
                                item["files"] += 1
                                item["bytes"] += entry.stat().st_size
                        except OSError:
                            continue
                if stack or item["files"] >= max_files:
                    item["truncated"] = True
            result[name] = item
        return result

    def list_area(self, name, limit=200):
        path = self.area(name)
        rows = []
        for entry in sorted(path.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if len(rows) >= limit:
                break
            try:
                stat = entry.stat()
            except OSError:
                continue
            rows.append({
                "name": entry.name,
                "path": str(entry),
                "dir": entry.is_dir(),
                "bytes": 0 if entry.is_dir() else stat.st_size,
                "mtime": stat.st_mtime,
            })
        return rows

    # ---------- 清理 ----------
    _UPLOAD_NAME = re.compile(r"[0-9a-f]{32}\.(?:png|jpg|jpeg|webp|gif)")

    @classmethod
    def image_names(cls, text):
        """从任意文本里抠出上传图片文件名（给 Engine 扫内存引用用）。"""
        return {match.group(0) for match in cls._UPLOAD_NAME.finditer(str(text or ""))}

    @classmethod
    def __clear_unused_uploads(cls, references=None):
        """删掉没被任何会话 / 当前内存引用的上传图片。

        引用 = 会话 JSONL 或调用方传入的引用集合（Engine 从内存记录里扫）。
        viewImage 按内容哈希命名，所以重复看同一张图不会重复占空间。
        """
        root = home() / "uploads"
        if not root.exists():
            return 0
        pattern = re.compile(rb"[0-9a-f]{32}\.(?:png|jpg|jpeg|webp|gif)")
        referenced = set(references or ())
        for path in session_dir().glob("session-*.jsonl"):
            try:
                for match in pattern.finditer(path.read_bytes()):
                    referenced.add(match.group(0).decode("ascii"))
            except OSError:
                continue

        removed = 0
        for entry in list(root.iterdir()):
            if not entry.is_file():
                continue
            if not re.fullmatch(r"[0-9a-f]{32}\.(?:png|jpg|jpeg|webp|gif)", entry.name):
                continue
            if entry.name in referenced:
                continue
            try:
                entry.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def clear(self, name, references=None, keep_path=None):
        """按区域的清理语义：

        artifacts → 整体清；uploads → 只清未引用图片；logs → 清空文件内容；
        sandbox → 清空临时目录；workspace → 只清 `tmp/`；sessions → 只清空会话。
        """
        name = str(name or "")
        if name == "uploads":
            return self.__clear_unused_uploads(references)
        if name == "logs":
            return self.__truncate_logs()
        if name == "sessions":
            return self.__clear_empty_sessions(keep_path)
        if name == "sandbox":
            return self.__clear_dir(self.area("sandbox"))
        if name == "projects":
            return self.__clear_dir(self.area("projects"))
        if name == "workspace":
            return self.__clear_dir(self.workspace() / "tmp")
        if name != "artifacts":
            raise ValueError("这个区域不能清理")
        return self.__clear_dir(self.area("artifacts"))

    @staticmethod
    def __clear_dir(root):
        import shutil

        if not root.exists():
            return 0
        removed = 0
        for entry in list(root.iterdir()):
            try:
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def __truncate_logs(self):
        """日志不删文件（可能还开着），只清空内容。"""
        root = self.area("logs")
        removed = 0
        if not root.exists():
            return 0
        for entry in list(root.rglob("*")):
            if not entry.is_file():
                continue
            try:
                with open(entry, "w", encoding="utf-8"):
                    pass
                removed += 1
            except OSError:
                continue
        return removed

    def __clear_empty_sessions(self, keep_path=None):
        """只删没有任何记录的会话（不碰有内容的 / 当前会话）。"""
        root = self.area("sessions")
        keep = str(keep_path or "")
        removed = 0
        for path in list(root.glob("session-*.jsonl")):
            if keep and str(path) == keep:
                continue
            try:
                if path.stat().st_size > 0:
                    continue
            except OSError:
                continue
            meta_path = path.with_name(path.name + ".meta.json")
            try:
                path.unlink()
                if meta_path.exists():
                    meta_path.unlink()
                removed += 1
            except OSError:
                continue
        return removed


disk = Disk()
