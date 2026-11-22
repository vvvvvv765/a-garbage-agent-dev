"""
场景层（配置层，不是主体系）：提示词增量 + 能力子集 + 安全默认值。

一个场景一个文件夹：
  Scenarios/<id>/scenario.json
  Scenarios/<id>/prompt.md

引擎保持场景无关；切换由 Engine.use_scenario 在轮次边界统一应用。
"""
from .core import (
    DEFAULT_SCENARIO,
    capabilities_for,
    common_capabilities,
    defaults_for,
    get_scenario,
    list_scenarios,
    prompt_for,
    public_scenarios,
)

__all__ = [
    "DEFAULT_SCENARIO",
    "capabilities_for",
    "common_capabilities",
    "defaults_for",
    "get_scenario",
    "list_scenarios",
    "prompt_for",
    "public_scenarios",
]
