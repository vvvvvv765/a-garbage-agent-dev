"""
bash 能力（能力体系的子体系）

声明依赖 workdir：由能力体系注入，执行命令时作为工作目录。
"""
import threading
from pathlib import Path

from Config import config

from .Executions import ExecutionCancelled, executions
from .Sandbox import sandbox
from .Shell import PersistentShell
from .Spec import CapabilitySpec


def bash_path():
    """bash 可执行文件：默认 spirit/shell/PortableGit；可用 engine.bash_path 覆盖。"""
    configured = config.get("engine.bash_path", "")
    if configured:
        return str(Path(configured))
    return str(
        Path(__file__).resolve().parent.parent
        / "shell" / "PortableGit" / "bin" / "bash.exe"
    )


class BashCapability:
    name = "bash"
    description = (
        "在同一个持久 bash 中执行命令，返回输出；cwd 固定在工作区。"
        "cd / export / source venv 会在命令之间保留（取消或超时会重开 shell）。"
        "读/写/替换文件优先用 readFile / writeFile / replaceInFile，"
        "查找用 searchFiles / findFiles——只有这些工具做不到时才用 bash。"
        "默认超时 30 秒；构建 / 下载 / 长任务用 timeout 参数调大（最长 300 秒）。"
        "输出过长会落盘到数据根 Artifacts/spill，用 readFile 按路径继续读。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令（推荐用这个参数名）"},
            "bashinput": {"type": "string", "description": "旧参数名，等同 command（兼容用）"},
            "timeout": {
                "type": "integer",
                "description": "本条命令的超时秒数（1–600，默认 30）",
            },
        },
        # required 留空：command / bashinput 二选一，运行时校验（兼容旧会话）
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self):
        self.__bash = bash_path()
        self.__workdir = None
        self.__shells = {}
        self.__shell_lock = threading.Lock()

    def __shell_for(self, session_id):
        key = str(session_id or "primary")
        with self.__shell_lock:
            shell = self.__shells.get(key)
            if shell is None:
                shell = PersistentShell()
                self.__shells[key] = shell
            return shell

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name,
            self.description,
            self.parameters,
            deps=("workdir",),
            timeout=330,   # 覆盖单条命令最长 300s；先让 bash 自己杀进程
            trust="untrusted",
        )

    def setup(self, deps):
        """能力体系在登记时注入声明过的依赖。"""
        workdir = deps.get("workdir")
        if self.__workdir and workdir != self.__workdir:
            self.__stop_shells()   # 换工作区：旧 shell 的 cd 状态作废
        self.__workdir = workdir

    def __stop_shells(self):
        with self.__shell_lock:
            shells = list(self.__shells.values())
            self.__shells.clear()
        for shell in shells:
            shell.stop()

    def dispose(self):
        self.__stop_shells()

    def run(self, arguments):
        command = str(arguments.get("command") or arguments.get("bashinput") or "")
        if not command.strip():
            return "command 不能为空（参数名用 command；旧名 bashinput 也接受）"
        if not Path(self.__bash).exists():
            return (
                f"bash 不存在：{self.__bash}"
                "（检查 config 的 engine.bash_path 或 shell/PortableGit）"
            )
        executions.check()
        sandbox.check_command(command)

        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            timeout = int(arguments.get("timeout") or config.get("engine.bash_timeout", 30))
        except (TypeError, ValueError):
            timeout = 30
        timeout = max(1, min(300, timeout))
        shell = self.__shell_for(getattr(execution, "session_id", ""))
        output, status, problem = shell.run(
            self.__workdir,
            sandbox.bash_env(self.__workdir),
            command,
            timeout=timeout,
            cancel=cancel,
            on_output=execution.emit if execution is not None else None,
        )
        if problem == "cancelled":
            detail = output.strip()
            raise ExecutionCancelled(
                "用户停止" + (f"\n取消前已捕获的输出：\n{detail}" if detail else "")
            )
        if problem == "timeout":
            hint = ""
            if any(name in command.lower() for name in ("msedge", "chrome", "firefox")):
                hint = (
                    "\n提示：浏览器可能弹了系统对话框并阻塞；请用 --headless "
                    "且 --user-data-dir 传绝对路径"
                )
            return (
                f"bash 命令超时，shell 已重开（cd / export 状态丢失）"
                f"\n可在 timeout 参数里调大（1–300 秒）{hint}\n{output}"
            )
        if problem == "exited":
            return f"shell 已退出（可能执行了 exit），下次调用会重开\n{output}"
        executions.check()
        if status not in (None, 0):
            # 命令失败必须让模型看见退出码，不能“无输出 = 成功”
            mark = f"[exit {status}]"
            return f"{output}\n{mark}" if output else mark
        return output
