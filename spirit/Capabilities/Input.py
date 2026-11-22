"""
能力对大模型的输入（模型 → 能力）

CPU 从数据表读到 tool_call 记录后，把它翻译成这个对象，再交给能力体系。
arguments 解析失败不抛异常，原因放 error，由能力体系回给模型。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityInput:
    call_id: str
    name: str
    raw_arguments: str              # 原字符串（上下文回填用）
    arguments: dict | None = None   # 已解析
    error: str | None = None        # 参数解析 / 校验失败的原因
