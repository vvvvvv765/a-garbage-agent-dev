"""命令灾难闸：bash / processStart 执行前的危险级别判定。

判定分级（**只有 deny 会真的拦**）：
  ok      正常命令 → 放行
  deny    灾难性目标（磁盘根、系统目录、用户主目录根、机器数据、引导 / 分区）→ 不可授权
  confirm 可能越界 / 不可逆的写法（内联危险原语、工作区外删除、下载后执行…）
          → **只作诊断分级，当前不接审批、不额外拦截**。这是有意的：
          闸的定位是“只挡会把机器搞坏的操作”，不做保姆；审批是成本，
          多问一次就多打断一次正常作业。要接审批前先对照
          《Agent项目构思》§〇「能力优先，不过度限制」。

这是**策略检查，不是内核隔离**：它能挡住常见灾难和手滑，挡不住针对性的绕过
（变量拼接、编码、写脚本再执行）。挡不住的部分靠审批、审计和快照恢复。

判定思路：
  1. 按 ; && || | 换行 切段，逐段看动词
  2. 删除 / 覆盖类动词把目标解析成真实路径再分类（工作区内 / 外 / 系统 / 机器数据）
  3. 解释器内联代码（python -c、powershell -Command…）扫危险原语
  4. 下载后直接执行、编码命令、重定向写系统路径 → 确认
"""
import os
import re
import tempfile
from pathlib import Path

OK, CONFIRM, DENY = "ok", "confirm", "deny"

_SEGMENT = re.compile(r"\|\||&&|[;|\n]")
_TOKEN = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:")
_PIPE_EXEC = re.compile(
    r"\|\s*(?:sh|bash|zsh|dash|python[0-9.]*|node|perl|ruby|iex|invoke-expression)\b",
    re.IGNORECASE,
)
_DOWNLOAD = re.compile(
    r"\b(?:curl|wget|iwr|invoke-webrequest|invoke-restmethod|start-bitstransfer)\b",
    re.IGNORECASE,
)
_ENCODED = re.compile(
    r"(?:^|\s)-(?:e|ec|en|enc|encodedcommand)\b(?=\s+[A-Za-z0-9+/=]{16,})"
    r"|frombase64string",
    re.IGNORECASE,
)
_DANGER_CODE = re.compile(
    r"\b(?:rmtree|os\.remove|os\.unlink|os\.rmdir|unlink|rm_sync|rmsync|rimraf|"
    r"remove-item|del\s|erase\s|rm\s+-|shred|truncate|"
    r"format\s|diskpart|mkfs|fdisk|dd\s+if=|reg\s+delete|bcdedit|vssadmin|"
    r"shutdown|restart-computer|stop-computer)\b",
    re.IGNORECASE,
)
_REDIRECT = re.compile(r"(?:^|\s)(?:\d?>>?)\s*([^\s;&|]+)")

_UNIX_DELETE = {"rm", "unlink", "shred"}
_WIN_DELETE = {
    "del", "erase", "rd", "rmdir", "remove-item", "ri",
    "clear-content", "srm", "sdelete",
}
_DISK_DENY = {
    "mkfs", "format", "diskpart", "fdisk", "parted", "wipefs",
    "format-volume", "clear-disk", "initialize-disk", "remove-partition",
}
_BOOT_DENY = {"bcdedit", "bootrec", "vssadmin", "wbadmin"}
_INTERPRETERS = {"python", "python3", "py", "node", "perl", "ruby", "php"}
_SHELLS = {"sh", "bash", "zsh", "dash", "cmd", "powershell", "pwsh"}
_VALUE_FLAGS = {
    "-s", "--size", "-n", "-path", "-literalpath", "-filter", "-include",
    "-exclude", "-destination", "-name", "-iname", "-type", "-maxdepth",
    "-mindepth", "-exec", "-execdir",
}


class Verdict:
    def __init__(self, level=OK, reason="", target="", category=""):
        self.level = level
        self.reason = str(reason or "")
        self.target = str(target or "")
        self.category = str(category or "")

    @property
    def ok(self):
        return self.level == OK


def _worse(left, right):
    rank = {OK: 0, CONFIRM: 1, DENY: 2}
    return left if rank[left.level] >= rank[right.level] else right


def _system_roots():
    roots = set()
    for key in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(key)
        if not value:
            continue
        try:
            roots.add(Path(value).resolve())
        except OSError:
            pass
    msys = _msys_root()
    if msys is not None:
        roots.add(msys)
    return roots


def _msys_root():
    """Git Bash 的根（PortableGit / Git for Windows）；找不到就 None。

    先看 PATH；桌面壳 / 服务进程的 PATH 常常没有 Git，再查常见安装位置。
    """
    import shutil

    candidates = []
    path = shutil.which("bash")
    if path:
        candidates.append(Path(path))
    candidates += [
        Path(r"D:\kaifa\Git"),
        Path(r"C:\Program Files\Git"),
        Path(r"C:\Program Files (x86)\Git"),
        Path(r"D:\wangj\AI\claude\shell\PortableGit"),
        Path(r"D:\wangj\AI\claude\shell\PortableGit\PortableGit"),
        # 打包版自带 bash：_internal/shell/PortableGit（本文件在 _internal/Capabilities）
        Path(__file__).resolve().parents[1] / "shell" / "PortableGit",
    ]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.name.lower() in {"git", "portablegit"} and resolved.exists():
            return resolved
        lowered = str(resolved).lower()
        if "git" in lowered and resolved.name.lower() in {"bash.exe", "sh.exe"}:
            for parent in resolved.parents:
                if parent.name.lower() in {"git", "portablegit"}:
                    return parent
    return None


def _strip_glob(text):
    for index, char in enumerate(text):
        if char in "*?[":
            return text[:index].rstrip("/\\") or "."
    return text


def _to_path(token, workdir):
    """把命令里的目标 token 归一成 Path；解析不了返回 None（按“需要确认”处理）。"""
    text = str(token or "").strip().strip("\"'")
    text = re.sub(r"^[&@]+", "", text)
    if not text:
        return None

    msys = _msys_root()
    # 家目录 / 变量
    if text == "~" or text.startswith("~/") or text.startswith("~\\"):
        rest = text[1:].lstrip("/\\")
        text = str(Path(workdir) / rest) if rest else str(workdir)
    text = re.sub(r"\$\{?HOME\}?", lambda _m: str(workdir), text, flags=re.IGNORECASE)
    text = re.sub(r"\$\{?env:userprofile\}?", lambda _m: str(workdir), text, flags=re.IGNORECASE)
    text = re.sub(r"%userprofile%", lambda _m: str(workdir), text, flags=re.IGNORECASE)
    text = re.sub(
        r"%systemroot%|%windir%",
        lambda _m: os.environ.get("SystemRoot", r"C:\Windows"),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\$\{?env:systemroot\}?", lambda _m: os.environ.get("SystemRoot", r"C:\Windows"),
                  text, flags=re.IGNORECASE)
    if "$" in text or "%" in text:
        return None   # 还有变量：静态解析不了

    # Git Bash 的 /c/... → C:\...
    match = re.match(r"^/([A-Za-z])(?:/(.*))?$", text)
    if match and Path(f"{match.group(1).upper()}:\\").exists():
        rest = (match.group(2) or "").replace("/", "\\")
        text = f"{match.group(1).upper()}:\\{rest}"
    elif text.startswith("/"):
        if text == "/tmp" or text.startswith("/tmp/"):
            return Path(tempfile.gettempdir()) / text[5:] if len(text) > 4 else Path(tempfile.gettempdir())
        if msys is not None:
            return (msys / text.lstrip("/")).resolve()
        return None

    text = _strip_glob(text)
    if text in {"", ".", "./"}:
        return Path(workdir).resolve()
    try:
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = Path(workdir) / path
        return path.resolve()
    except (OSError, ValueError):
        return None


def _classify(path, workdir, protected, system_roots):
    if path is None:
        return CONFIRM, "目标无法静态解析"
    try:
        target = path.resolve()
    except OSError:
        return CONFIRM, "目标无法解析"
    if target == workdir:
        return DENY, "目标是工作区根目录（会清空整台机器的文件）"
    if workdir in target.parents:
        return OK, ""
    for root in protected:
        try:
            root = Path(root).resolve()
        except OSError:
            continue
        if target == root or root in target.parents:
            return DENY, f"{target} 是机器数据 / 密钥，不允许动"
    home = Path.home().resolve()
    if target == home or target == home.parent:
        return DENY, f"{target} 是用户主目录，不允许整目录操作"
    if target.parent == target:
        return DENY, f"{target} 是磁盘根目录"
    for root in system_roots:
        if target == root or root in target.parents:
            return DENY, f"{target} 在系统目录里"
    for temp_root in (Path(tempfile.gettempdir()), Path(workdir) / "tmp"):
        if target == temp_root or temp_root in target.parents:
            return OK, ""
    return CONFIRM, f"{target} 在工作区外"


def _is_flag(token, windows):
    if token.startswith("-"):
        return True
    return bool(windows and re.match(r"^/[A-Za-z]+$", token))


def _targets(args, windows):
    """从参数里挑出目标（跳过选项和选项的值）。"""
    targets = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        lowered = token.lower()
        if lowered in _VALUE_FLAGS:
            skip_next = True
            continue
        if token == "--":
            continue
        if _is_flag(token, windows):
            continue
        targets.append(token)
    return targets


def _redirection_verdict(segment, workdir, protected, system_roots):
    worst = Verdict()
    for match in _REDIRECT.finditer(segment):
        token = match.group(1)
        if token.lower() in {"/dev/null", "nul", "$null"}:
            continue
        path = _to_path(token, workdir)
        level, reason = _classify(path, workdir, protected, system_roots)
        if level != OK:
            worst = _worse(worst, Verdict(level, reason, token, "redirect"))
    return worst


def _interpreter_verdict(verb, args, segment):
    lowered = segment.lower()
    if _ENCODED.search(segment):
        return Verdict(DENY, "命令里带编码 / Base64 执行，无法静态看清", segment[:120], "encoded")
    if _DOWNLOAD.search(segment) and _PIPE_EXEC.search(segment):
        return Verdict(CONFIRM, "下载后直接交给解释器执行", segment[:120], "download-exec")
    if _DANGER_CODE.search(lowered) and verb not in {"echo", "printf", "cat", "type"}:
        return Verdict(CONFIRM, "命令里包含删除 / 磁盘 / 注册表等危险原语", segment[:120], "primitive")
    return Verdict()


def _verb_verdict(verb, args, segment, workdir, protected, system_roots):
    windows = verb in _WIN_DELETE
    if verb in _UNIX_DELETE or verb in _WIN_DELETE:
        targets = _targets(args, windows)
        worst = Verdict()
        for token in targets:
            path = _to_path(token, workdir)
            level, reason = _classify(path, workdir, protected, system_roots)
            worst = _worse(worst, Verdict(level, reason, token, "delete"))
        return worst

    if verb == "truncate":
        targets = _targets(args, False)
        if not targets:
            return Verdict()
        path = _to_path(targets[-1], workdir)
        level, reason = _classify(path, workdir, protected, system_roots)
        return Verdict(level, reason, targets[-1], "truncate")

    if verb == "dd":
        for token in args:
            if token.lower().startswith("of="):
                value = token[3:]
                if value.startswith("/dev/") or value.startswith("\\\\.\\"):
                    return Verdict(DENY, "dd 直接写块设备", value, "disk")
                path = _to_path(value, workdir)
                level, reason = _classify(path, workdir, protected, system_roots)
                if level == OK:
                    level, reason = CONFIRM, f"dd 会整块覆盖 {value}"
                return Verdict(level, reason, value, "dd")
        return Verdict(CONFIRM, "dd 是底层写入，需要确认", "", "dd")

    if verb in _DISK_DENY or verb.startswith("mkfs"):
        return Verdict(DENY, f"{verb} 会改分区 / 格式化磁盘", "", "disk")
    if verb in _BOOT_DENY:
        return Verdict(DENY, f"{verb} 会改引导 / 备份 / 卷影", "", "boot")

    if verb == "find":
        lowered = [item.lower() for item in args]
        if "-delete" in lowered:
            narrowed = any(item in lowered for item in ("-name", "-iname", "-path", "-regex"))
            targets = _targets(args, False)
            target = targets[0] if targets else "."
            if narrowed:
                return Verdict(CONFIRM, "find -delete 会按条件批量删除", target, "find-delete")
            path = _to_path(target, workdir)
            level, reason = _classify(path, workdir, protected, system_roots)
            return Verdict(level, reason, target, "find-delete")
        return Verdict()

    if verb == "git":
        lowered = [item.lower() for item in args]
        if "clean" in lowered and any(item.startswith("-") and "f" in item for item in lowered):
            return Verdict(CONFIRM, "git clean 会删掉未跟踪文件", "", "git-clean")
        return Verdict()

    if verb == "robocopy":
        if any(item.lower() in {"/mir", "/purge"} for item in args):
            targets = _targets(args, True)
            path = _to_path(targets[-1] if targets else ".", workdir)
            level, reason = _classify(path, workdir, protected, system_roots)
            return Verdict(level, reason, targets[-1] if targets else "", "robocopy")
        return Verdict()

    if verb == "reg":
        sub = next((item.lower() for item in args if not item.startswith("-")), "")
        if sub in {"add", "delete", "import", "copy"}:
            return Verdict(CONFIRM, f"reg {sub} 会改注册表", "", "registry")
        return Verdict()

    if verb == "sc":
        sub = next((item.lower() for item in args if not item.startswith("-")), "")
        if sub in {"create", "delete", "config", "start", "stop", "failure"}:
            return Verdict(CONFIRM, f"sc {sub} 会改服务", "", "service")
        return Verdict()

    if verb == "net":
        sub = next((item.lower() for item in args if not item.startswith("-")), "")
        if sub in {"user", "localgroup", "stop", "start"}:
            return Verdict(CONFIRM, f"net {sub} 会改账户 / 服务", "", "account")
        return Verdict()

    if verb == "netsh":
        lowered = " ".join(args).lower()
        if "advfirewall" in lowered or "winhttp" in lowered:
            return Verdict(CONFIRM, "netsh 会改防火墙 / 代理设置", "", "firewall")
        return Verdict()

    if verb == "schtasks" or verb == "at":
        return Verdict(CONFIRM, "计划任务修改需要确认", "", "schedule")

    if verb in {"taskkill", "stop-process", "pkill", "kill", "killall"}:
        return Verdict(CONFIRM, "结束进程需要确认", "", "process")

    if verb in {"shutdown", "reboot", "poweroff", "halt", "restart-computer",
                "stop-computer", "init"}:
        if verb == "init" and args and args[0] not in {"0", "6"}:
            return Verdict()
        return Verdict(CONFIRM, "关机 / 重启会中断这台机器", "", "power")

    if verb in {"takeown", "icacls"}:
        return Verdict(CONFIRM, "修改文件权限 / 所有者需要确认", "", "acl")

    if verb == "cipher" and any(item.lower() == "/w" for item in args):
        return Verdict(CONFIRM, "cipher /w 会擦除磁盘空闲空间", "", "wipe")

    if verb in {"certutil", "bitsadmin", "mshta", "rundll32"}:
        lowered = " ".join(args).lower()
        if "http" in lowered or "urlcache" in lowered or "download" in lowered:
            return Verdict(CONFIRM, "可能下载并执行外部内容", "", "download")

    if verb in _INTERPRETERS or verb in _SHELLS:
        lowered = [item.lower() for item in args]
        if verb in _SHELLS and any(item in {"-c", "/c", "-command", "-commandwithargs"} for item in lowered):
            inner = segment
            for marker in ("-c ", "/c ", "-Command ", "-command "):
                index = inner.lower().find(marker.lower())
                if index >= 0:
                    inner = inner[index + len(marker):]
                    break
            return _inspect(inner, workdir, protected, system_roots, depth=1)
        return _interpreter_verdict(verb, args, segment)

    return Verdict()


def _segment_verdict(segment, workdir, protected, system_roots, depth):
    tokens = [item.strip("\"'") for item in _TOKEN.findall(segment)]
    tokens = [item for item in tokens if item]
    if not tokens:
        return Verdict()

    index = 0
    while index < len(tokens) and (
        _ASSIGN.match(tokens[index])
        or tokens[index].lower() in {"sudo", "doas", "env", "exec", "command", "builtin", "time"}
    ):
        index += 1
    if index >= len(tokens):
        return Verdict()

    verb = tokens[index].lower().replace("/", "\\").rsplit("\\", 1)[-1]
    if verb.endswith(".exe"):
        verb = verb[:-4]
    args = tokens[index + 1:]

    verdict = _verb_verdict(verb, args, segment, workdir, protected, system_roots)
    return _worse(verdict, _redirection_verdict(segment, workdir, protected, system_roots))


def _first_verb(text):
    """命令第一段的第一个动词（跳过 FOO=1 / sudo 之类的前缀）。"""
    for segment in _SEGMENT.split(str(text or "")):
        tokens = [item.strip("\"'") for item in _TOKEN.findall(segment)]
        tokens = [item for item in tokens if item]
        index = 0
        while index < len(tokens) and (
            _ASSIGN.match(tokens[index])
            or tokens[index].lower() in {"sudo", "doas", "env", "exec", "command", "builtin", "time"}
        ):
            index += 1
        if index >= len(tokens):
            continue
        verb = tokens[index].lower().replace("/", "\\").rsplit("\\", 1)[-1]
        return verb[:-4] if verb.endswith(".exe") else verb
    return ""


def _inspect(text, workdir, protected, system_roots, depth=0):
    text = str(text or "").strip()
    if not text:
        return Verdict()
    if _FORK_BOMB.search(text):
        return Verdict(DENY, "fork bomb", "", "forkbomb")

    # 命令替换 / 反引号：里面的命令也要过闸（echo $(rm -rf …) 不能靠 echo 豁免）
    for match in re.finditer(r"\$\(([^()]*)\)|`([^`]*)`", text):
        inner = (match.group(1) or match.group(2) or "").strip()
        if not inner:
            continue
        verdict = _inspect(inner, workdir, protected, system_roots, depth + 1)
        if verdict.level == DENY:
            return verdict

    worst = Verdict()
    for segment in _SEGMENT.split(text):
        segment = segment.strip()
        if not segment:
            continue
        verdict = _segment_verdict(segment, workdir, protected, system_roots, depth)
        worst = _worse(worst, verdict)
        if worst.level == DENY:
            return worst

    # 解析不出段首动词的写法（for / xargs / -exec / 子 shell）：
    if not worst.ok:
        return worst
    lowered = text.lower()
    if re.search(r"\b(?:xargs|parallel)\b[^|]*\b(?:rm|del|rd|remove-item)\b", lowered):
        return Verdict(CONFIRM, "通过管道批量删除，无法静态确认目标", "", "xargs")
    if re.search(r"-exec(?:dir)?\s+(?:rm|del|rd|remove-item)\b", lowered):
        return Verdict(CONFIRM, "通过 find -exec 删除，无法静态确认目标", "", "find-exec")
    if _ENCODED.search(text):
        return Verdict(DENY, "命令里带编码 / Base64 执行，无法静态看清", "", "encoded")
    if _DOWNLOAD.search(text) and _PIPE_EXEC.search(text):
        return Verdict(CONFIRM, "下载后直接交给解释器执行", "", "download-exec")
    if _DANGER_CODE.search(lowered) and not re.match(r"^\s*(?:echo|printf|cat|type)\b", lowered):
        return Verdict(CONFIRM, "命令里包含删除 / 磁盘 / 注册表等危险原语", "", "primitive")
    return worst


def inspect_command(command, workdir, protected=()):
    """返回 Verdict；workdir 是 bash 的工作目录，protected 是机器数据 / 密钥根。"""
    try:
        workdir = Path(workdir or ".").resolve()
    except OSError:
        workdir = Path(".").resolve()
    protected = [Path(item) for item in (protected or ()) if item]
    return _inspect(command, workdir, protected, _system_roots())
