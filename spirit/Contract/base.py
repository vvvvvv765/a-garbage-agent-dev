"""
该模块为 自定义协议，用于Agent计算机思想，该协议约定了是 CPU 体系与其他体系之间的交流，体系与体系之间的交流

而该协议运用的场景：其他体系向：cup的汇报 ，同体系之间的交流，CPU 对其他体系的控制。

所以共用同一个协议，但因为 字段 与 值 的不同，则可以运用到不同的场景中，具体字段意义见 Contract 类定义


"""
import threading
from collections import deque
from dataclasses import dataclass



@dataclass
class Contract:
    start:bool | None = None # 该信号段是用于是否开始整个程序，用于启动循环。相当于开机键
    stop:bool | None = None  # 该信号段是用于是否结束整个程序，用于结束循环。相当于关机键 [暂时废弃]
    skip: bool | None = None  # 该信号段用于是否跳过本次循环

    SI: bool | None = None # 该信号段是用于表示整个体系再运行时是否有错，表示该体系无任何错误
    should_process: bool | None = None  # 该信号段用于体系之间，表示该体系是否处理该数据


@dataclass(frozen=True)
class Instruction:
    """信息表里的指令：CPU 写给某个体系，让它处理某份数据。

    - 只有 CPU 写，目标体系读
    - "运输数据" = 让该体系开始处理这条数据；数据本身不动
    - **不可变**：边沿信号写入是“追加一条新事实”，不是改旧事实
    """
    target: str                 # 目标体系
    action: str                 # 动作（start / stop / ...，由目标体系解释）
    data: dict | None = None    # 数据引用：{地址, seq 起止} 或 ticket
    seq: int = 0                # 指令序号（轮次边界 / 渲染 epoch）


class InstructionQueue:
    """边沿触发的指令队列：start / stop 每条都要被消费，不能被后一条合并。"""

    def __init__(self):
        self.__items = deque()
        self.__lock = threading.Lock()

    def push(self, instruction):
        with self.__lock:
            self.__items.append(instruction)

    def take(self):
        with self.__lock:
            items = list(self.__items)
            self.__items.clear()
            return items

    def __len__(self):
        with self.__lock:
            return len(self.__items)


@dataclass
class ThinkingControl:
    """思考控制：开关 + 强度。

    和 Contract 一样是 CPU 写给体系读的控制对象，只是多带一个强度字段。
    effort 的取值由 provider 适配层解释（DeepSeek：low / medium / high）。
    """
    should_process: bool = False   # 思考是否开启
    effort: str = "medium"        # 思考强度





