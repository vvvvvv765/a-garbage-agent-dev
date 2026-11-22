"""
异常处理体系：每个体系一个 handler。

流程：
  体系捕获异常 -> handler.report(异常, 位置)
    -> 产出一条异常数据（写进数据表的 exception 虚拟地址，可落盘）
    -> 显示体系自己从表里看到它

异常不送大模型（GPU 不选这个地址）。
"""
import time
from dataclasses import dataclass

from Memory import mem, EXCEPTION
from Log import log


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class FaultRecord:
    system: str
    where: str
    kind: str
    message: str
    time: str

    def to_dict(self):
        return {
            "system": self.system,
            "where": self.where,
            "kind": self.kind,
            "message": self.message,
            "time": self.time,
        }


class FaultHandler:
    """某个体系的异常处理体系（持有体系名）。"""

    def __init__(self, system, sink):
        self.system = system
        self.__sink = sink

    def report(self, error, where=""):
        self.__sink.report(FaultRecord(
            self.system, where, type(error).__name__, str(error), _now()
        ))

    def report_message(self, message, where=""):
        self.__sink.report(FaultRecord(
            self.system, where, "Error", str(message), _now()
        ))


class FaultSystem:
    def __init__(self):
        self.__handlers = {}

    def for_system(self, name):
        """取某个体系专属的 handler（同一个体系复用同一个）。"""
        if name not in self.__handlers:
            self.__handlers[name] = FaultHandler(name, self)
        return self.__handlers[name]

    def report(self, record):
        """异常数据：写数据表（显示体系自己会看到）+ 写日志。"""
        mem.submit(EXCEPTION, record.to_dict())
        log.error(record.system, f"{record.where}: {record.kind}: {record.message}")


faults = FaultSystem()
