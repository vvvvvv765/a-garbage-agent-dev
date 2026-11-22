"""
能力对大模型的输出（能力 → 模型）

能力体系把 run() 的返回值包装成这个对象：
  截断 / spill → 写数据表 tool_output → GPU 下一轮配对成 function_call_output
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilityResult:
    """能力可以返回它，用来附带结构化元数据（目前用于图片附件）。

    普通能力继续直接返回 str；只有需要额外字段时（例如 viewImage）才用这个。
    """
    content: str
    meta: dict = field(default_factory=dict)
    ok: bool = True   # 能力可以明确报告失败（浏览器脚本非零退出 / 权限被挡）


@dataclass(frozen=True)
class CapabilityOutput:
    call_id: str
    content: str
    ok: bool = True
    meta: dict = field(default_factory=dict)

    def to_record(self):
        """写进数据表 tool_output 虚拟地址的形状（GPU 从这里读）。"""
        return {
            "call_id": self.call_id,
            "output": self.content,
            "meta": dict(self.meta),
        }
