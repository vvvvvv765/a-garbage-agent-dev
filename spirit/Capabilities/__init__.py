"""
能力体系：Agent 通用计算机的所有能力（工具、命令、以后的一切外设）。

每个能力是能力体系的子体系；能力的主体系负责：
  - 注册表（加载 / 启停 / 注销）
  - 说明聚合（给大模型看的 tools）
  - 执行与后处理（线程池 / 校验 / 截断 / spill）
  - 结果写数据表

三个契约见 System.py 顶部。
"""
from .Spec import CapabilitySpec
from .Input import CapabilityInput
from .Output import CapabilityOutput, CapabilityResult
from .Registry import Registry, RegistryError, Entry
from .System import CapabilitySystem, capabilities
