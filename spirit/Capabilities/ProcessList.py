"""
processList：列出后台进程（含已结束的）。
"""
from .Processes import processes
from .Spec import CapabilitySpec


class ProcessListCapability:
    name = "processList"
    description = "列出后台进程（运行中 / 已结束），带进程 ID、状态和输出行数。"
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=10,
            side_effect="read",
        )

    def run(self, arguments):
        entries = processes.list()
        if not entries:
            return "没有后台进程"
        lines = []
        for entry in entries:
            command = entry.command.replace("\n", " ")
            if len(command) > 80:
                command = command[:80] + "…"
            lines.append(
                f"{entry.id}  {entry.status()}  输出 {len(entry.lines)} 行  {command}"
            )
        return "\n".join(lines)
