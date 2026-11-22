"""
能力（能力体系的子体系）的标准接口。

必须实现：
  spec() -> CapabilitySpec        我怎么被调用、我要什么配置、我要什么依赖
  run(arguments: dict) -> str     执行；返回值就是要回给大模型的内容

可选实现（由能力体系在对应时机调）：
  configure(config: dict)         登记时注入每能力配置
  setup(deps: dict)               登记时注入依赖（只给声明过的）
  dispose()                       注销时释放资源

异常 / 超时：
  - 体系给每个能力一个独立的异常 handler（记录里带 capability:<名字>）
  - 超时由 spec.timeout 或全局 engine.capability_timeout 决定；
    超时 = 不再等它，不是杀掉线程（子进程类能力请自己设 kill 超时）
  - 想自己上报异常？声明 deps=("faults",)，用 setup 拿到的 faults 报
"""
from typing import Protocol

from .Spec import CapabilitySpec


class Capability(Protocol):
    def spec(self) -> CapabilitySpec:
        ...

    def run(self, arguments: dict) -> str:
        ...
