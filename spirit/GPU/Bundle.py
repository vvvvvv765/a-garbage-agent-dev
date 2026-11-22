"""
中立消息包：GPU 加工完交给 ModI 发出去的那份东西。

单独一个模块，避免 core / ModI / Summary 之间互相 import 成环。
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextBundle:
    """中立消息包：适配层决定怎么映射到具体 provider。"""
    instructions: str
    messages: tuple
    meta: dict = field(default_factory=dict)
