"""
轮次级取消令牌（中立）：CPU 置位，ModO / Summary / 沙箱抓取 / 审批都查。

它只写一个事件，不写信息表指令——所以外部线程取消不会破坏 CPU 单线程调度。
"""
import contextvars
import threading


class CancelToken:
    def __init__(self):
        self.__event = threading.Event()

    def clear(self):
        self.__event.clear()

    def set(self):
        self.__event.set()

    def is_set(self):
        return self.__event.is_set()

    def wait(self, timeout=None):
        return self.__event.wait(timeout)

    def sleep(self, seconds):
        """可被取消的等待；返回 True 表示被取消。"""
        return self.__event.wait(max(0.0, float(seconds)))


_DEFAULT = CancelToken()
_CURRENT = contextvars.ContextVar("spirit_cancel", default=None)


class _CancelProxy:
    __slots__ = ()

    def __getattr__(self, name):
        target = _CURRENT.get() or _DEFAULT
        return getattr(target, name)


token = _CancelProxy()


def use(cancel_token):
    return _CURRENT.set(cancel_token)


def unuse(marker):
    _CURRENT.reset(marker)


def default_token():
    return _DEFAULT
