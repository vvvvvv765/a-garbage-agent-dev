"""
打包 / 解包能力：zip / tar / tar.gz / tar.bz2 / tar.xz / 单文件 gz / bz2 / xz。

硬规则（正确性，不是权限）：
  - 解包成员不许绝对路径、不许 ..、不许软 / 硬链接 / 设备文件
  - 每个成员最终路径必须仍落在 dest 里面
  - 默认限制 10 万个文件 / 解压后 2GB，防压缩炸弹把盘写满
"""
import bz2
import gzip
import lzma
import os
import re
import stat
import tarfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from .Files import human_size, resolve
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec

MAX_FILES = 100000
MAX_TOTAL = 2 * 1024 * 1024 * 1024
MAX_LIST = 1000


class _LimitReached(Exception):
    pass


def _safe_member(name):
    raw = str(name or "").replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise ValueError(f"压缩包里有绝对路径：{raw}")
    parts = [part for part in PurePosixPath(raw).parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"压缩包里有 .. 路径：{raw}")
    if not parts:
        return None
    return Path(*parts)


def _inside(root, target):
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _kind(path, fmt=""):
    fmt = str(fmt or "").strip().lower()
    if fmt in ("zip", "tar", "gz", "bz2", "xz"):
        if fmt in ("tar.gz", "tgz"):
            return "tar"
        return fmt
    low = path.name.lower()
    if low.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz", ".tar")):
        return "tar"
    if low.endswith(".zip"):
        return "zip"
    if low.endswith(".gz"):
        return "gz"
    if low.endswith(".bz2"):
        return "bz2"
    if low.endswith(".xz"):
        return "xz"
    try:
        with open(path, "rb") as file:
            head = file.read(512)
    except OSError:
        return ""
    if head[:4] == b"PK\x03\x04":
        return "zip"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    if head[:2] == b"\x1f\x8b":
        return "gz"
    if head[:3] == b"BZh":
        return "bz2"
    if head[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if head[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    return ""


def _default_stem(path):
    name = path.name
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tbz2", ".txz",
                   ".zip", ".tar", ".gz", ".bz2", ".xz"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)] or "extracted"
    return name + ".out"


def _copy_limited(source, target, remaining):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    written = 0
    try:
        with open(temp, "wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > remaining:
                    raise _LimitReached("解压后大小超过上限")
                output.write(chunk)
        os.replace(temp, target)
    finally:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
    return written


def _extract_zip(path, dest, password="", overwrite=True):
    count = 0
    total = 0
    skipped = 0
    limit_hit = ""
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                safe = _safe_member(info.filename)
                if safe is None:
                    continue
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError(f"压缩包里有软链接：{info.filename}")
                target = dest / safe
                if not _inside(dest, target):
                    raise ValueError(f"成员越出目标目录：{info.filename}")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if count >= MAX_FILES:
                    limit_hit = f"文件数超过上限 {MAX_FILES}"
                    break
                if target.exists() and not overwrite:
                    skipped += 1
                    continue
                try:
                    source = archive.open(info, pwd=password.encode() if password else None)
                except RuntimeError as error:
                    raise ValueError(f"{info.filename} 无法打开（{error}）") from error
                try:
                    total += _copy_limited(source, target, MAX_TOTAL - total)
                finally:
                    source.close()
                count += 1
    except (zipfile.BadZipFile, RuntimeError) as error:
        raise ValueError(f"ZIP 解包失败：{error}") from error
    return count, total, skipped, limit_hit


def _extract_tar(path, dest, overwrite=True):
    count = 0
    total = 0
    skipped = 0
    limit_hit = ""
    try:
        with tarfile.open(path, "r:*") as archive:
            for member in archive:
                if member.isdir():
                    safe = _safe_member(member.name)
                    if safe is not None:
                        (dest / safe).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    if member.issym() or member.islnk() or member.isdev():
                        raise ValueError(f"压缩包里有链接 / 设备文件：{member.name}")
                    continue
                safe = _safe_member(member.name)
                if safe is None:
                    continue
                target = dest / safe
                if not _inside(dest, target):
                    raise ValueError(f"成员越出目标目录：{member.name}")
                if count >= MAX_FILES:
                    limit_hit = f"文件数超过上限 {MAX_FILES}"
                    break
                if target.exists() and not overwrite:
                    skipped += 1
                    continue
                source = archive.extractfile(member)
                if source is None:
                    continue
                try:
                    total += _copy_limited(source, target, MAX_TOTAL - total)
                finally:
                    source.close()
                count += 1
    except tarfile.TarError as error:
        raise ValueError(f"tar 解包失败：{error}") from error
    return count, total, skipped, limit_hit


def _open_stream(path, kind):
    if kind == "gz":
        return gzip.open(path, "rb")
    if kind == "bz2":
        return bz2.open(path, "rb")
    if kind == "xz":
        return lzma.open(path, "rb")
    raise ValueError(f"不是单文件压缩流：{kind}")


class ArchiveListCapability:
    name = "archiveList"
    description = (
        "列压缩包内容（zip / tar / tar.gz / tar.bz2 / tar.xz / gz / bz2 / xz）："
        "成员名、原始大小、压缩后大小。7z 暂不支持，可用 bash 调 7z。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "压缩包路径"},
            "limit": {"type": "integer", "description": "最多列多少项，默认 200"},
        },
        "required": ["file"],
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
        try:
            path = resolve(self.__workdir, arguments.get("file"))
            if not path.exists() or not path.is_file():
                return f"列目录失败：文件不存在 {path}"
            limit = min(MAX_LIST, max(1, int(arguments.get("limit", 200))))
        except SandboxDenied:
            raise
        except Exception as error:
            return f"列目录失败：{error}"
        kind = _kind(path)
        if not kind:
            return f"列目录失败：认不出压缩格式（{path.name}）"
        if kind == "7z":
            return "列目录失败：7z 暂不支持；可用 bash 调系统 7z / tar"
        lines = [f"### 压缩包 {path}（{kind}，{human_size(path.stat().st_size)}）"]
        try:
            if kind == "zip":
                with zipfile.ZipFile(path) as archive:
                    infos = archive.infolist()
                    lines.append(f"成员：{len(infos)} 个")
                    for info in infos[:limit]:
                        flag = "/" if info.is_dir() else ""
                        lines.append(
                            f"  {info.filename}{flag} "
                            f"原始 {human_size(info.file_size)} · 压缩 {human_size(info.compress_size)}"
                        )
                    if len(infos) > limit:
                        lines.append(f"…（还有 {len(infos) - limit} 项）")
            elif kind == "tar":
                with tarfile.open(path, "r:*") as archive:
                    members = archive.getmembers()
                    lines.append(f"成员：{len(members)} 个")
                    for member in members[:limit]:
                        flag = "/" if member.isdir() else ""
                        lines.append(
                            f"  {member.name}{flag} 原始 {human_size(member.size)}"
                        )
                    if len(members) > limit:
                        lines.append(f"…（还有 {len(members) - limit} 项）")
            else:
                lines.append(f"单文件压缩流：解压后写到 {_default_stem(path)}")
                with _open_stream(path, kind) as stream:
                    sample = stream.read(1)
                lines.append(f"解压后大小需实际解压（首字节 {len(sample)}）")
        except Exception as error:
            return "\n".join(lines) + f"\n\n读取失败：{error}"
        return "\n".join(lines)


class ArchiveExtractCapability:
    name = "archiveExtract"
    description = (
        "解压 zip / tar / tar.gz / tar.bz2 / tar.xz / gz / bz2 / xz 到工作区目录。"
        "默认解到压缩包同级的同名文件夹；拒绝绝对路径 / .. / 链接。"
        "支持 zip 密码；默认限制 10 万文件 / 2GB。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "压缩包路径"},
            "dest": {"type": "string", "description": "解压目标文件夹；默认按压缩包名生成"},
            "output": {"type": "string", "description": "单文件压缩流的输出文件名"},
            "password": {"type": "string", "description": "zip 密码（可选）"},
            "overwrite": {"type": "boolean", "description": "已存在文件是否覆盖，默认 true"},
        },
        "required": ["file"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            trust="untrusted", side_effect="write", timeout=300, max_inline=5000,
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        try:
            path = resolve(self.__workdir, arguments.get("file"))
            if not path.exists() or not path.is_file():
                return f"解压失败：文件不存在 {path}"
            kind = _kind(path)
            if not kind:
                return f"解压失败：认不出压缩格式（{path.name}）"
            if kind == "7z":
                return "解压失败：7z 暂不支持；可用 bash 调系统 7z / tar"
            dest_arg = str(arguments.get("dest") or "").strip()
            if dest_arg:
                dest = resolve(self.__workdir, dest_arg)
            else:
                dest = resolve(self.__workdir, str(path.parent / _default_stem(path)))
            dest.mkdir(parents=True, exist_ok=True)
            overwrite = bool(arguments.get("overwrite", True))
            password = str(arguments.get("password") or "")
        except SandboxDenied:
            raise
        except Exception as error:
            return f"解压失败：{error}"

        try:
            if kind == "zip":
                count, total, skipped, limit_hit = _extract_zip(
                    path, dest, password, overwrite
                )
            elif kind == "tar":
                count, total, skipped, limit_hit = _extract_tar(
                    path, dest, overwrite
                )
            else:
                output_name = str(arguments.get("output") or "").strip()
                target_name = output_name or _default_stem(path)
                safe = _safe_member(target_name)
                if safe is None:
                    return "解压失败：output 不能为空"
                target = dest / safe
                if not _inside(dest, target):
                    return "解压失败：output 越出目标目录"
                if target.exists() and not overwrite:
                    return f"解压跳过：{target} 已存在"
                with _open_stream(path, kind) as source:
                    total = _copy_limited(source, target, MAX_TOTAL)
                count, skipped, limit_hit = 1, 0, ""
        except _LimitReached as error:
            return f"解压中止：{error}（已解出部分文件，请检查目标目录）"
        except SandboxDenied:
            raise
        except Exception as error:
            return f"解压失败：{error}"

        lines = [
            f"### 解压 {path.name} → {dest}",
            f"解出：{count} 个文件 · {human_size(total)}",
        ]
        if skipped:
            lines.append(f"跳过：{skipped} 个已存在文件（overwrite=false）")
        if limit_hit:
            lines.append(f"注意：{limit_hit}，已停止")
        return "\n".join(lines)


def _walk_sources(sources, skip_path):
    files = []
    for source in sources:
        if source.is_file():
            if source.resolve() != skip_path.resolve():
                files.append(source)
        elif source.is_dir():
            for root, dirs, names in os.walk(source):
                dirs[:] = [name for name in dirs if not Path(root, name).is_symlink()]
                for name in names:
                    item = Path(root, name)
                    if item.is_symlink() or item.resolve() == skip_path.resolve():
                        continue
                    files.append(item)
    return files


class ArchiveCreateCapability:
    name = "archiveCreate"
    description = (
        "把文件 / 文件夹打包成 zip / tar / tar.gz / tar.bz2 / tar.xz。"
        "sources 里每一项按自己的名字作为包内顶层；默认限制 2GB。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "dest": {"type": "string", "description": "输出压缩包路径，扩展名决定格式"},
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要打包的文件 / 文件夹路径",
            },
            "format": {
                "type": "string",
                "enum": ["auto", "zip", "tar", "tar.gz", "tar.bz2", "tar.xz"],
                "description": "格式，默认按 dest 扩展名判断",
            },
        },
        "required": ["dest", "sources"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            trust="internal", side_effect="write", timeout=300, max_inline=4000,
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        try:
            dest = resolve(self.__workdir, arguments.get("dest"))
            raw_sources = arguments.get("sources") or []
            if not isinstance(raw_sources, list) or not raw_sources:
                return "打包失败：sources 不能为空"
            sources = [resolve(self.__workdir, item) for item in raw_sources]
            missing = [str(item) for item in sources if not item.exists()]
            if missing:
                return "打包失败：不存在 " + "、".join(missing)
            dest.parent.mkdir(parents=True, exist_ok=True)
        except SandboxDenied:
            raise
        except Exception as error:
            return f"打包失败：{error}"

        fmt = str(arguments.get("format") or "auto").lower()
        if fmt == "auto":
            low = dest.name.lower()
            if low.endswith(".zip"):
                fmt = "zip"
            elif low.endswith(".tar.gz") or low.endswith(".tgz"):
                fmt = "tar.gz"
            elif low.endswith(".tar.bz2") or low.endswith(".tbz2"):
                fmt = "tar.bz2"
            elif low.endswith(".tar.xz") or low.endswith(".txz"):
                fmt = "tar.xz"
            elif low.endswith(".tar"):
                fmt = "tar"
            else:
                return "打包失败：认不出格式；请给 zip / tar / tar.gz 扩展名或 format"
        files = _walk_sources(sources, dest)
        if not files:
            return "打包失败：没有可打包的文件"
        total = sum(item.stat().st_size for item in files)
        if total > MAX_TOTAL:
            return f"打包失败：源文件共 {human_size(total)}，超过 2GB 上限"
        if len(files) > MAX_FILES:
            return f"打包失败：文件数 {len(files)} 超过 {MAX_FILES} 上限"

        temp = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
        written = 0
        try:
            if fmt == "zip":
                with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as archive:
                    for source, arcname in _archive_names(files, sources):
                        archive.write(source, arcname)
                        written += 1
            else:
                mode = {
                    "tar": "w", "tar.gz": "w:gz",
                    "tar.bz2": "w:bz2", "tar.xz": "w:xz",
                }.get(fmt)
                if mode is None:
                    return f"打包失败：不支持的格式 {fmt}"
                with tarfile.open(temp, mode) as archive:
                    for source, arcname in _archive_names(files, sources):
                        archive.add(source, arcname=arcname, recursive=False)
                        written += 1
            os.replace(temp, dest)
        except Exception as error:
            try:
                if temp.exists():
                    temp.unlink()
            except OSError:
                pass
            return f"打包失败：{error}"
        return (
            f"### 打包完成 {dest}\n"
            f"文件：{written} 个 · 源 {human_size(total)} · 包 {human_size(dest.stat().st_size)}"
        )


def _archive_names(files, sources):
    """包内路径：文件用自己的名字；文件夹保留相对文件夹的路径。"""
    for source in sources:
        if source.is_file():
            for item in files:
                if item == source:
                    yield item, item.name
        elif source.is_dir():
            for item in files:
                try:
                    relative = item.relative_to(source)
                except ValueError:
                    continue
                yield item, str(Path(source.name) / relative).replace("\\", "/")
