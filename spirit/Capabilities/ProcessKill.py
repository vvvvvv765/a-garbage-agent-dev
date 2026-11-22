"""
processKill：结束一个后台进程。
"""
from .Processes import processes
from .Spec import CapabilitySpec


class ProcessKillCapability:
    name = "processKill"
    description = "结束一个后台进程（先 terminate，3 秒不退再 kill）。"
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "进程 ID，如 p1（推荐）"},
            "pid": {"type": "string", "description": "旧参数名，等同 id"},
        },
        "required": [],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(self.name, self.description, self.parameters, timeout=15)

    def run(self, arguments):
        pid = str(arguments.get("id") or arguments.get("pid") or "").strip()
        if not pid:
            return "需要 id（processList 返回的进程 ID；旧参数名 pid 也接受）"
        entry = processes.get(pid)
        if entry is None:
            return f"没有这个进程：{pid}（用 processList 看有哪些）"
        if not entry.running:
            return f"{pid} 已经结束了（退出码 {entry.process.returncode}）"
        processes.kill(entry)
        return f"已结束 {pid}（退出码 {entry.process.returncode}）"
