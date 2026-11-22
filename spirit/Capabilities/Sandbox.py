"""
沙箱子体系（能力体系的子体系）：硬边界。

它和 CPU 的安全子体系分工：
  - 沙箱：路径能不能碰、命令能不能跑 —— **硬拒绝**
  - 安全：要不要问用户 —— 审批

现在 backend = "policy"：
  - 文件能力：相对路径必须落在工作区内；绝对路径要命中的允许根；
    会话 / 日志 / 配置文件永远拒绝；符号链接按真实路径判
  - bash / 后台进程：cwd 固定工作区；清洗环境变量（Key / SPIRIT_* / 云凭据）；
    命令规则黑名单；禁止用 .. 逃出工作区
  - 真正的 OS 隔离（Job Object / 容器 / 独立用户）留给 backend 接缝，
    换后端时能力只认这里的 resolve / check_command / bash_env

诚实边界：bash 终究是子进程，policy 模式拦不住所有花招（例如写脚本再执行、
通过 Windows 绝对路径读文件）。挡不住的部分靠审批 + 审计，不要把它当 VM。
"""
import fnmatch
import os
import re
from pathlib import Path

from Config import config
from Paths import artifacts_dir, config_file, home as data_home, log_dir, session_dir

from .CommandGuard import DENY as GUARD_DENY
from .CommandGuard import inspect_command

DEFAULT_DENY_PATHS = [
    "~/.ssh",
    "~/.aws",
    "~/.gnupg",
    "~/.git-credentials",
    "~/.npmrc",
    "~/.docker/config.json",
]

DEFAULT_DENY_COMMANDS = [
    r"\brm\s+(-\S+\s+)*[/~]",              # rm -rf / 或 ~（含 $(...) 包裹）
    r"\bmkfs(\.|\s)",
    r"\bdiskpart\b",
    r"\bformat\s+[a-z]:",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
]

SECRET_ENV = {
    "DEEPSEEK_API_KEY",
    "TAVILY_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "GOOGLE_APPLICATION_CREDENTIALS",
}
SECRET_PREFIXES = ("AZURE_", "SPIRIT_", "ANTHROPIC_")


class SandboxDenied(Exception):
    """沙箱拒绝（能力体系会把它变成一条 ok=False 的工具结果）。

    kind / target 让上层能分辨"越界但可授权"与"绝对禁止"：
      outside  = 不在工作区/允许路径里，可以问用户授权
      protected / denied / invalid / rule = 不提供授权入口
    """

    def __init__(self, message, kind="denied", target=""):
        super().__init__(message)
        self.kind = str(kind)
        self.target = str(target or "")


class Sandbox:
    def __init__(self):
        self.__session_allow = []   # 本次进程内长期允许（UI「本次会话」）
        self.__once_allow = []      # 只对当前一批调用有效（UI「允许一次」）
        self.last_denial = {}
        self.reload()

    def reload(self):
        self.workspace_only = bool(
            config.get("engine.sandbox.workspace_only", False)
        )
        self.home_is_workspace = bool(
            config.get("engine.sandbox.home_is_workspace", True)
        )
        self.scrub_env = bool(config.get("engine.sandbox.scrub_env", True))

        self.allow_roots = [
            Path(str(item)).expanduser().resolve()
            for item in (config.get("engine.sandbox.allow_paths", []) or [])
        ]
        self.deny_patterns = [
            str(item)
            for item in (config.get("engine.sandbox.deny_paths", DEFAULT_DENY_PATHS) or [])
        ]
        # 灾难闸的命令规则由代码定义（跟他的设计走）；旧配置里的 deny_commands 不再生效
        self.command_patterns = [
            re.compile(str(item), re.IGNORECASE) for item in DEFAULT_DENY_COMMANDS
        ]

    # ---------- 路径 ----------
    def resolve(self, workdir, path):
        """把模型给的路径落成真实路径；越界就拒绝。"""
        if "\x00" in str(path or ""):
            raise SandboxDenied("路径包含 NUL 字符", "invalid", str(path or ""))
        raw = Path(str(path or ".")).expanduser()
        base = Path(workdir or ".").resolve()
        target = (raw if raw.is_absolute() else base / raw).resolve()

        if self.is_protected(target):
            raise SandboxDenied(f"{target} 是引擎数据（会话 / 日志 / 配置），不允许访问", "protected", target)
        if self.__denied(target):
            raise SandboxDenied(f"{target} 命中禁止路径", "denied", target)
        if self.workspace_only and not self.__allowed_roots(target, base):
            allowed = "、".join(str(item) for item in self.allow_roots) or "（无）"
            if self.__granted(target):
                return target
            raise SandboxDenied(
                f"{target} 不在工作区内（允许根：{base}；额外：{allowed}）",
                "outside",
                target,
            )
        return target

    def __granted(self, target):
        return any(self.__within(target, root) for root in (self.__session_allow + self.__once_allow))

    def grant_once(self, path):
        """允许一次：当前这一批调用有效，批末由能力体系清掉。"""
        root = Path(str(path)).expanduser().resolve()
        if root not in self.__once_allow:
            self.__once_allow.append(root)
        return root

    def grant_session(self, path):
        """本次进程内长期允许（不写配置）。"""
        root = Path(str(path)).expanduser().resolve()
        if root not in self.__session_allow:
            self.__session_allow.append(root)
        return root

    def clear_once(self):
        self.__once_allow.clear()

    def __allowed_roots(self, target, base):
        if self.__within(target, base):
            return True
        # 能力产物区：框架落盘的大结果放在这里（工作区之外），
        # 模型要能按 meta.path 读回全文，所以单独放行。
        try:
            artifacts = artifacts_dir().resolve()
        except OSError:
            artifacts = None
        if artifacts is not None and self.__within(target, artifacts):
            return True
        return any(self.__within(target, root) for root in self.allow_roots)

    def within(self, path, workdir):
        """布尔版：给遍历 / 列目录过滤用，不抛异常。"""
        try:
            target = Path(path).resolve()
            base = Path(workdir or ".").resolve()
            return (
                not self.is_protected(target)
                and not self.__denied(target)
                and (
                    not self.workspace_only
                    or self.__allowed_roots(target, base)
                )
            )
        except Exception:
            return False

    def is_protected(self, path):
        try:
            target = Path(path).resolve()
        except Exception:
            return True
        config_path = Path(config_file()).resolve()
        if target == config_path:
            return True
        # 同目录下 config.json.bak / config.json.corrupt-* / .config.json.*.tmp 也是密钥载体
        if target.parent == config_path.parent and target.name.startswith(config_path.name):
            return True
        # 项目资产（数据根/Projects）是给模型读写的作业数据，不是引擎内部账本；
        # 即使 session 目录被配置成数据根，也不能把它一起保护掉。
        try:
            from Paths import home as _home
            projects = (Path(_home()) / "Projects").resolve()
            if self.__within(target, projects):
                return False
        except Exception:
            pass
        for root in (Path(session_dir()).resolve(), Path(log_dir()).resolve()):
            if self.__within(target, root):
                return True
        return False

    def __within(self, target, root):
        try:
            return target == root or root in target.parents
        except Exception:
            return False

    def __denied(self, target):
        text = str(target).replace("\\", "/").lower()
        for pattern in self.deny_patterns:
            pattern = str(pattern).replace("\\", "/")
            if pattern.startswith("~/"):
                pattern = str(Path.home() / pattern[2:]).replace("\\", "/")
            pattern = pattern.lower()
            if fnmatch.fnmatch(text, pattern) or text == pattern or text.startswith(pattern + "/"):
                return True
        return False

    # ---------- 命令 ----------
    def check_command(self, command):
        text = str(command or "")
        for pattern in self.command_patterns:
            if pattern.search(text):
                raise SandboxDenied(f"命令命中禁止规则：{pattern.pattern}")
        # 引擎自己的数据（配置 / 会话 / 日志）：不管绝对路径还是相对名都拦
        lowered = text.replace("\\", "/").lower()
        # Git Bash 的 /c/users/... 和 WSL 的 /mnt/c/...：先归一到 c:/...
        normalized = re.sub(r"(?<![a-z0-9])/mnt/([a-z])/", lambda m: m.group(1) + ":/", lowered)
        normalized = re.sub(r"(?<![a-z0-9])/([a-z])/", lambda m: m.group(1) + ":/", normalized)
        for root in (config_file(), session_dir(), log_dir()):
            token = str(Path(root).resolve()).replace("\\", "/").lower()
            if token and (token in lowered or token in normalized):
                raise SandboxDenied("命令里出现引擎数据路径（配置 / 会话 / 日志）")
        workdir = Path(config.get("engine.workdir", "") or ".").resolve()
        home = Path(config_file()).resolve().parent
        if workdir == home:
            # 工作区就是数据根时，光写文件名也能读到
            if re.search(r"(^|[\s'\"=/])(config\.json|Session_Storage|audit\.jsonl)([\s'\"/]|$)",
                         lowered):
                raise SandboxDenied("命令里出现机器数据文件名", "protected")

        # 灾难闸：删除 / 磁盘 / 注册表 / 下载执行 / 解释器内联代码
        protected = [config_file(), session_dir(), log_dir()]
        if Path(data_home()).resolve() != workdir:
            protected.append(data_home())
        for pattern in self.deny_patterns:
            text_pattern = str(pattern)
            if text_pattern.startswith("~/"):
                protected.append(Path.home() / text_pattern[2:])
        verdict = inspect_command(text, workdir, protected)
        if verdict.level == GUARD_DENY:
            raise SandboxDenied(
                f"灾难闸拒绝：{verdict.reason}", "catastrophic", verdict.target
            )

    # 子进程环境白名单（Windows + Git Bash + Python/venv 必需的那批；其余一律不传）
    ENV_ALLOW = (
        "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
        "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL",
        "USERNAME", "USERDOMAIN", "COMPUTERNAME", "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "OS",
        "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES",
        "MSYSTEM", "MSYS", "MINGW_PREFIX", "MSYS2_PATH_TYPE",
    )

    def bash_env(self, workdir):
        """给 bash / 后台进程的环境：**白名单构造**，不再复制父进程再删。

        - 只保留白名单里的系统变量 + 用户配置的 `engine.sandbox.env_allow`
        - HOME / USERPROFILE 指到工作区；TEMP / TMP 指到工作区 tmp
        - scrub_env=False 时退回旧行为（整份复制后删敏感名单）
        """
        workdir_path = Path(workdir or ".").resolve()
        home = str(workdir_path)
        if not self.scrub_env:
            env = dict(os.environ)
            for key in list(env):
                if key in SECRET_ENV or key.startswith(SECRET_PREFIXES):
                    env.pop(key, None)
        else:
            allowed = {name.lower() for name in self.ENV_ALLOW}
            for name in (config.get("engine.sandbox.env_allow", []) or []):
                allowed.add(str(name).lower())
            env = {}
            for key, value in os.environ.items():
                if key.lower() in allowed:
                    env[key] = value
        if self.home_is_workspace:
            env["HOME"] = home
            env["USERPROFILE"] = home
        temp = workdir_path / "tmp"
        try:
            temp.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        env["TEMP"] = str(temp)
        env["TMP"] = str(temp)
        env["SPIRIT_SANDBOX"] = "workspace"
        return env


    # ---------- 给 CPU 的预检 ----------
    FILE_PATHS = {
        "readFile": "path",
        "writeFile": "path",
        "replaceInFile": "path",
        "listDir": "path",
        "searchFiles": "path",
        "findFiles": "path",
        "processStart": "cwd",
    }

    def precheck(self, name, arguments):
        """执行前的硬边界检查：返回 (ok, reason)。拒绝详情在 `last_denial`。"""
        arguments = arguments or {}
        self.last_denial = {}
        try:
            if name in ("bash", "processStart"):
                if name == "bash":
                    command = str(arguments.get("command") or arguments.get("bashinput") or "")
                else:
                    command = str(arguments.get("command") or "")
                self.check_command(command)
            if name in self.FILE_PATHS:
                field = self.FILE_PATHS[name]
                workdir = config.get("engine.workdir", "") or os.getcwd()
                self.resolve(workdir, arguments.get(field, "."))
        except SandboxDenied as error:
            self.last_denial = {
                "kind": getattr(error, "kind", "denied"),
                "target": getattr(error, "target", ""),
                "message": str(error),
            }
            if name in ("bash", "processStart"):
                self.last_denial["command"] = str(
                    arguments.get("command") or arguments.get("bashinput") or ""
                )
            return False, f"沙箱拒绝：{error}"
        except (ValueError, OSError, TypeError) as error:
            # 非法路径（NUL / 超长 / 类型不对）：一律按拒绝处理
            return False, f"沙箱拒绝：路径不合法（{error}）"
        return True, ""


sandbox = Sandbox()
