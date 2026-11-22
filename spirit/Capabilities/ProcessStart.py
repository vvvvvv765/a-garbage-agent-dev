"""
processStart：后台启动一条命令，立刻返回进程 ID。
"""
from .Files import resolve
from .Processes import processes
from .Sandbox import SandboxDenied, sandbox
from .Spec import CapabilitySpec


class ProcessStartCapability:
    name = "processStart"
    description = (
        "在后台启动一条 bash 命令（不等待结束），返回进程 ID。"
        "用 processOutput 看输出、processKill 收掉；适合长任务、起服务。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 bash 命令"},
            "cwd": {"type": "string", "description": "工作目录；默认当前工作目录"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self):
        self.__workdir = None

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters,
            deps=("workdir",), timeout=15,
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def dispose(self):
        """引擎关机 / 注销时，把还活着的后台进程收掉。"""
        processes.stop_all()

    def run(self, arguments):
        command = str(arguments.get("command", "")).strip()
        if not command:
            return "命令为空"
        try:
            sandbox.check_command(command)
            cwd = resolve(self.__workdir, arguments.get("cwd", "."))
            entry = processes.start(
                command, cwd=str(cwd), env=sandbox.bash_env(cwd)
            )
        except SandboxDenied:
            raise
        except Exception as error:
            return f"启动失败：{error}"
        return (
            f"已启动 {entry.id}（pid {entry.process.pid}）：{command}\n"
            f"用 processOutput 看输出，processKill 收掉"
        )
