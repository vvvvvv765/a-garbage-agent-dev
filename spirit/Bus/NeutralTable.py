"""
该模块为中立表，主要用于解决，协议信息 交换时的模块相互导入问题。姑且看作计算机的线路

体系给CPU的 key = 体系名Signal  CPU给体系 key = CPU体系名

登记规则（2026-11-18）：
  - Contract（报告 / 控制）：按设计会被反复覆盖，直接覆盖
  - 句柄 / 其他对象：同一个 key 换个对象再登记 = 启动顺序出事，**报错**
  - 确实要换（BIOS 重建客户端、CPU 重启新队列）传 replace=True
"""
import contextvars
import threading

from Contract import Contract, ThinkingControl

# 协议对象（报告 / 电平控制）：按设计会被反复覆盖
PROTOCOL_TYPES = (Contract, ThinkingControl)


class NeutralTable:
    def __init__(self, parent=None):
        self.__NT = {}
        self.__parent = parent
        self.__lock = threading.Lock()   # 保护"检查 + 写入"这一对操作

    def register(self, key, obj, replace=False):
        with self.__lock:
            old = self.__NT.get(key)
            if old is not None and old is not obj and not replace:
                report_pair = (
                    isinstance(old, PROTOCOL_TYPES)
                    and isinstance(obj, PROTOCOL_TYPES)
                )
                if not report_pair:
                    raise RuntimeError(
                        f"信息表 key 重复登记：{key}"
                        f"（旧 {type(old).__name__} / 新 {type(obj).__name__}）"
                    )
            self.__NT[key] = obj

    def get(self, key):
        with self.__lock:
            value = self.__NT.get(key)
        if value is None and self.__parent is not None:
            return self.__parent.get(key)
        return value


# 默认总线 + 会话级总线代理（会话总线以默认总线为父，天然拿到能力体系 / BIOS 等全局资源）
_DEFAULT = NeutralTable()
_CURRENT = contextvars.ContextVar("spirit_bus", default=None)


class _NTProxy:
    __slots__ = ()

    def __getattr__(self, name):
        target = _CURRENT.get() or _DEFAULT
        return getattr(target, name)


NT = _NTProxy()


def use(table):
    return _CURRENT.set(table)


def unuse(token):
    _CURRENT.reset(token)


def default_table():
    return _DEFAULT
