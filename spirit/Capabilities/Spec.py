"""
能力说明（给大模型看的形状 + 给注册表看的元信息）

一份 spec 同时回答三件事：
  1. 模型怎么调用它        → name / description / parameters（JSON Schema）
  2. 它自己要什么配置      → config_schema
  3. 它要体系注入什么依赖  → deps
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    description: str
    parameters: dict                       # 给大模型的输入接口（JSON Schema）
    config_schema: dict = field(default_factory=dict)   # 每能力配置的形状
    deps: tuple = ()                       # 依赖声明，如 ("workdir",)
    max_inline: int = 4000                 # 超过就落盘（spill）
    timeout: float | None = None           # 本次调用最多等多少秒；None = 用全局默认
    trust: str = "internal"                # internal | untrusted（结果里是否可能带外部指令）
    side_effect: str = "write"             # read | write | external（批内调度 + 只读判断）
