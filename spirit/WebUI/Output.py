"""
Web 渲染出口（渲染体系的子体系）：把显示事件广播给所有 SSE 连接。

浏览器可能同时开几条 EventSource（刷新 / 重连），队列不能共用——
共用的话事件会被摊薄，正文会丢字。所以每个连接一条队列，事件统一广播。

队列设计（2026-11-20）：
  - **相邻流式片段合并**：assistant_delta / reasoning_delta 如果紧挨着同一个
    类型，就拼进队尾那一条。长回复从几千条事件压成很少几条，慢客户端也不容易
    把 2000 的容量撑爆。
  - **满了优先丢可再生的**：先丢 usage / 状态类旧事件，最后才动流式片段；
    正文丢了还有 assistant_final（整段）兜底，状态类丢了无所谓。
"""
import queue
import threading
import time
from collections import deque

_MERGE_TYPES = {"assistant_delta", "reasoning_delta", "tool_delta"}
_MAXSIZE = 2000


class EventQueue:
    """单条 SSE 连接的队列：合并流式片段 + 满时优先丢可再生事件。"""

    def __init__(self, maxsize=_MAXSIZE):
        self.maxsize = int(maxsize)
        self.__items = deque()
        self.__lock = threading.Lock()
        self.__cond = threading.Condition(self.__lock)

    # 给 publish 用
    def put_nowait(self, event):
        event = dict(event)
        kind = event.get("type")
        with self.__cond:
            if kind in _MERGE_TYPES and self.__items:
                tail = self.__items[-1]
                same_target = (
                    kind != "tool_delta"
                    or tail.get("call_id") == event.get("call_id")
                )
                same_session = (
                    (tail.get("session") or "primary")
                    == (event.get("session") or "primary")
                )
                if tail.get("type") == kind and same_target and same_session:
                    merged = dict(tail)
                    merged["text"] = str(tail.get("text", "")) + str(event.get("text", ""))
                    self.__items[-1] = merged
                    self.__cond.notify()
                    return
            if len(self.__items) >= self.maxsize:
                drop_at = next(
                    (index for index, item in enumerate(self.__items)
                     if item.get("type") not in _MERGE_TYPES),
                    0,
                )
                del self.__items[drop_at]
            self.__items.append(event)
            self.__cond.notify()

    # 给 SSE 生成器用（和 queue.Queue.get 同形状）
    def get(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self.__cond:
            while not self.__items:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise queue.Empty
                self.__cond.wait(remaining)
            return self.__items.popleft()

    def get_nowait(self):
        with self.__cond:
            if not self.__items:
                raise queue.Empty
            return self.__items.popleft()

    def qsize(self):
        with self.__lock:
            return len(self.__items)


_subscribers = set()
_lock = threading.Lock()


def publish(event):
    """把一条显示事件发给所有在线连接（没有连接就丢掉）。"""
    with _lock:
        subscribers = list(_subscribers)
    for target in subscribers:
        try:
            target.put_nowait(event)
        except Exception:
            pass


def has_subscribers():
    """当前有没有打开的页面/客户端在收事件（审批必须有界面才等）。"""
    with _lock:
        return bool(_subscribers)


def subscribe():
    """新连接登记一条队列。"""
    target = EventQueue(_MAXSIZE)
    with _lock:
        _subscribers.add(target)
    return target


def unsubscribe(target):
    """连接断开。"""
    with _lock:
        _subscribers.discard(target)


def attach(engine):
    """交给浏览器：控制台不再打，事件走广播（只通过引擎的门面接线）。"""
    engine.attach_display(publish, console=False)
