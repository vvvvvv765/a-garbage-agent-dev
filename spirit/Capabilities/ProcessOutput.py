"""
processOutput：按 offset 分页读后台进程的输出。
"""
from .Processes import processes
from .Spec import CapabilitySpec


class ProcessOutputCapability:
    name = "processOutput"
    description = (
        "读后台进程的输出。按 offset/limit 分页；返回里会给出 next_offset，"
        "接着读时把它传给 offset。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "进程 ID，如 p1（推荐）"},
            "pid": {"type": "string", "description": "旧参数名，等同 id"},
            "offset": {"type": "integer", "description": "从第几行开始，默认 0"},
            "limit": {"type": "integer", "description": "最多读多少行，默认 200"},
        },
        "required": [],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=10,
            trust="untrusted", side_effect="read",
        )

    def run(self, arguments):
        pid = str(arguments.get("id") or arguments.get("pid") or "").strip()
        if not pid:
            return "需要 id（processList 返回的进程 ID；旧参数名 pid 也接受）"
        entry = processes.get(pid)
        if entry is None:
            return f"没有这个进程：{pid}（用 processList 看有哪些）"

        offset = max(0, int(arguments.get("offset", 0)))
        limit = max(1, min(int(arguments.get("limit", 200)), 1000))
        with entry.lock:
            total = len(entry.lines)
            chunk = entry.lines[offset:offset + limit]

        header = f"# {pid} {entry.status()}；共 {total} 行，显示 {offset}–{min(total, offset + limit)}"
        if not chunk:
            return header + "\n（这一段没有输出）"
        body = "\n".join(chunk)
        end = offset + len(chunk)
        if end < total:
            body += f"\n…（next_offset={end}）"
        return f"{header}\n{body}"
