"""
轮次号（中立工具）：CPU 每处理一次用户输入 = 一轮。

为什么中立：日志 / 审计 / 用量 / 渲染要能在同一个轮次号下串成一条线，
但这些体系都不该 import CPU。CPU 在轮次边界调 begin()，其他人只读 current()。

- 进程内从 1 开始递增；0 = 还没有开始任何一轮
- 只活在进程内存里，不落盘；恢复出来的旧记录轮次号是 0
"""
import threading


class TurnCounter:
    def __init__(self):
        self.__lock = threading.Lock()
        self.__current = 0

    def begin(self):
        """开一轮：返回新的轮次号（只由 CPU 在轮次边界调）。"""
        with self.__lock:
            self.__current += 1
            return self.__current

    def current(self):
        """当前轮次号；0 = 还没有开始任何一轮。"""
        with self.__lock:
            return self.__current


turn = TurnCounter()
