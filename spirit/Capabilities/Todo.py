"""
todoWrite / todoRead：待办清单。

存在数据表的 todo 地址（最新一条生效）——跟着会话落盘，切换会话 / 重启后还在。
GPU 不认识这个地址，不会送进模型上下文；模型想看得自己调 todoRead。
"""
from .Spec import CapabilitySpec

STATUS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}


def _format(items):
    if not items:
        return "（没有待办）"
    lines = []
    for index, item in enumerate(items, 1):
        mark = STATUS.get(item.get("status"), "[ ]")
        lines.append(f"{index}. {mark} {item.get('text', '')}")
    return "\n".join(lines)


class TodoWriteCapability:
    name = "todoWrite"
    description = (
        "写入待办清单（整份覆盖）。每项 text 必填；status 可选 pending / in_progress / done。"
        "多步任务先写清单，做完一项就更新它。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "待办列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "done"],
                        },
                    },
                    "required": ["text"],
                },
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=10,
            deps=("todo",),
        )

    def setup(self, deps):
        self.__store = deps["todo"]

    def run(self, arguments):
        raw = arguments.get("items")
        if not isinstance(raw, list):
            return "items 必须是数组"

        items = []
        for entry in raw:
            if isinstance(entry, str):
                text, status = entry.strip(), "pending"
            elif isinstance(entry, dict):
                text = str(entry.get("text", "")).strip()
                status = str(entry.get("status", "pending"))
            else:
                continue
            if not text:
                continue
            if status not in STATUS:
                status = "pending"
            items.append({"text": text, "status": status})

        self.__store.save(items)
        if not items:
            return "待办为空，已清空"
        return _format(items)


class TodoReadCapability:
    name = "todoRead"
    description = "读当前待办清单。"
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=10,
            side_effect="read", deps=("todo",),
        )

    def setup(self, deps):
        self.__store = deps["todo"]

    def run(self, arguments):
        return _format(self.__store.load())
