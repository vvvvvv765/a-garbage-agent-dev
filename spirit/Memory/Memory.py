"""
内存体系：按虚拟地址存数据 + 常驻 worker 并发接收。

设计要点：
  - 虚拟地址 = 每种数据的名字（见 Addresses.py）
  - 生产者 submit(address, payload)（任意线程）→ FIFO 队列 → worker 单写
  - 顺序：单消费者 + FIFO；seq 在 worker 写入时分配
  - 回执：submit 发 ticket，flush 等 worker 处理到该 ticket
"""
import contextvars
import os
import queue
import threading
from collections import deque
from dataclasses import dataclass

from Log import log
from Turn import turn

# 瞬态地址的容量上限：渲染线程真死了也不会无界增长（正常轮末就清空）
TRANSIENT_MAXLEN = 20000

# 提交队列上限：生产者比 worker 快时**背压**（submit 阻塞），而不是无界吃内存。
# 数据是真实日志，不能丢；等 worker 消化是唯一正确的降级。
QUEUE_MAX = max(1, int(os.environ.get("SPIRIT_MEMORY_QUEUE", "100000") or 100000))


@dataclass
class Record:
    seq: int
    address: str
    payload: object
    turn: int = 0        # 写入时的轮次号（恢复出来的旧记录是 0）


class Memory:
    def __init__(self):
        self.__lock = threading.Lock()
        self.persist = None    # 会话级落盘器（默认用全局 persist）
        self.__seq = 0
        self.__records = []   # 全局有序日志（真源）
        self.__views = {}     # 虚拟地址 -> 视图
        self.__last = {}      # 虚拟地址 -> 最后一条的 seq（O(1) 水位查询）
        self.__floor = 0      # 已退役边界：seq <= floor 的冷记录不在内存里（磁盘还在）

        self.__queue = queue.Queue(maxsize=QUEUE_MAX)
        self.__cond = threading.Condition()
        # 入队锁和回执条件变量必须分开：队列满时 submit 会阻塞在 put 上，
        # 如果此时还拿着 __cond，worker 就没法更新 processed → 永远腾不出位置（死锁）。
        # 同一把入队锁保证“票号顺序 = 入队顺序”，flush 的语义不变。
        self.__submit_lock = threading.Lock()
        self.__submitted = 0
        self.__processed = 0
        self.__worker = None
        self.__worker_lock = threading.Lock()

        # 瞬态地址：不 seq、不落盘、轮末清空（传输中的形态）
        self.__transient = {}
        self.__transient_total = {}   # 绝对写入计数：deque 挤掉旧片段后，显示靠它算游标
        self.__transient_lock = threading.Lock()

        # 有新数据就通知（显示流靠它等，不空转）——条件属于表，不属于任何体系
        self.__data_cond = threading.Condition()
        self.__revision = 0

    # ---------- 生命周期 ----------
    def start(self):
        with self.__worker_lock:
            if self.__worker is not None and self.__worker.is_alive():
                return
            self.__worker = threading.Thread(
                target=self.__loop, name="MemoryWorker", daemon=True
            )
            self.__worker.start()

    def stop(self):
        with self.__worker_lock:
            worker = self.__worker
            if worker is None:
                return
            self.__worker = None
        try:
            self.__queue.put(None, timeout=5)
        except queue.Full:
            log.warning("Memory", "stop: queue full, worker 可能来不及收到退出信号")
        worker.join(timeout=5)

    @property
    def queue_maxsize(self):
        """提交队列上限（背压阈值）；诊断 / 测试用。"""
        return self.__queue.maxsize

    # ---------- 体系门面（给 CPU 的同步口：父调自己的子体系，经这里） ----------
    def consume(self, stream, should_stop=None, epoch=0):
        """处理一条模型流（委托子体系 ModO）：解析事件、写表、返回工具调用。"""
        from .ModO import modo   # 延迟导入：ModO 依赖本包初始化，顶层导入会成环
        return modo.consume(stream, should_stop, epoch)

    def save(self, path=None):
        """把新记录落盘（委托子体系 Persist）。"""
        from .Persist import persist   # 延迟导入：Persist → Faults → Memory，顶层会成环
        store = self.persist or persist
        return store.save(path)

    # ---------- 生产者 ----------
    def submit(self, address, payload):
        """产生即存：任意线程可调；返回 ticket（给回执用）。

        队列有上限（QUEUE_MAX）：满了就**阻塞**，给生产者施加背压——
        数据是真实日志，不能丢，等 worker 消化是唯一正确的降级。
        """
        self.start()
        # 分配 ticket 和入队必须是同一步：先拿大号、后入队会让 flush 提前满足。
        # 但“同一步”用的是 __submit_lock（不是 __cond）——put 可能在阻塞，
        # 拿 __cond 会把 worker 的回执路径堵死。
        with self.__submit_lock:
            with self.__cond:
                self.__submitted += 1
                ticket = self.__submitted
            self.__queue.put((ticket, address, payload))
        return ticket

    def flush(self):
        """等到当前已有的提交都被 worker 写进内存。"""
        with self.__cond:
            target = self.__submitted
            while self.__processed < target:
                self.__cond.wait(timeout=1)

    # ---------- 读 ----------
    def records(self):
        """全局日志快照（按 seq 有序）。调用前想拿最新，先 flush()。"""
        with self.__lock:
            return list(self.__records)

    def view(self, address):
        """某个虚拟地址的快照。"""
        with self.__lock:
            return list(self.__views.get(address, []))

    def snapshot(self):
        """数据表的读接口：冲刷后给出全局有序快照。"""
        self.flush()
        return self.records()

    def title_hint(self, length=24):
        """会话标题：第一条有文字的用户消息前 N 字（未落盘时给界面用）。"""
        try:
            records = self.records()
            for record in records:
                if record.address != "user":
                    continue
                payload = record.payload
                text = payload.get("text") if isinstance(payload, dict) else payload
                text = str(text or "").strip()
                if text:
                    return text[:length]
        except Exception:
            pass
        return ""

    def records_after(self, seq):
        """seq 之后的记录。

        主表按 seq 连续追加；退役后最前面的 seq 是 `floor+1`，
        所以“下标 = seq - floor”。请求的水位比 floor 还旧时从 0 开始。
        """
        with self.__lock:
            start = max(0, int(seq) - self.__floor)
            return list(self.__records[start:])

    def last_seq(self, address=None):
        """最后一个 seq（O(1)）：不传 address = 整张表的水位。"""
        with self.__lock:
            if address is None:
                return self.__seq
            return self.__last.get(address, 0)

    def records_floor(self):
        """已退役边界：seq <= floor 的冷记录不在内存（磁盘上还有）。"""
        with self.__lock:
            return self.__floor

    # ---------- 冷热分层 ----------
    def retire_before(self, seq):
        """把 seq 之前的冷记录从内存退役（**不删磁盘**）。

        只有确认已落盘（persist.saved_seq >= seq）才动手；否则返回 0，
        由下一次构建/落盘后再试。用法 / 摘要 / 待办这类小记录留在视图里，
        上下文、回放、用量都还找得到它们。
        """
        try:
            seq = int(seq or 0)
        except (TypeError, ValueError):
            return 0
        if seq <= 0:
            return 0
        self.flush()
        try:
            from .Persist import persist
            store = self.persist or persist
            if int(store.saved_seq) < seq:
                return 0
        except Exception:
            return 0

        keep_views = {"usage", "summary", "todo"}
        with self.__lock:
            if seq <= self.__floor:
                return 0
            index = 0
            while index < len(self.__records) and self.__records[index].seq <= seq:
                index += 1
            dropped = index
            if dropped:
                self.__records = self.__records[index:]
            for address, items in self.__views.items():
                if address in keep_views:
                    continue
                self.__views[address] = [item for item in items if item.seq > seq]
            self.__floor = seq
        return dropped

    def restore(self, records, floor=0, views=None, last_seq=0):
        """启动恢复：直接铺表（不经队列），保留原 seq 与退役边界。

        records：主表（seq > floor）；views：摘要 / 用量 / 待办这类小记录的视图；
        last_seq：文件里的最大 seq（新记录从这里往后编号）。
        """
        with self.__lock:
            self.__records = list(records)
            self.__views = {
                address: list(items) for address, items in (views or {}).items()
            }
            self.__last = {}
            for record in self.__records:
                self.__last[record.address] = record.seq
            for items in self.__views.values():
                for record in items:
                    if record.seq > self.__last.get(record.address, 0):
                        self.__last[record.address] = record.seq
            floor = int(floor or 0)
            high = int(last_seq or 0)
            for record in self.__records:
                high = max(high, record.seq)
            for items in self.__views.values():
                for record in items:
                    high = max(high, record.seq)
            self.__seq = max(high, floor)
            self.__floor = floor
            self.__submitted = 0
            self.__processed = 0
        self.__bump()

    # ---------- 瞬态地址 ----------
    def push_transient(self, address, item):
        """追加一段瞬态数据（不 seq、不落盘）；有容量上限，超了丢最旧。"""
        with self.__transient_lock:
            self.__transient.setdefault(
                address, deque(maxlen=TRANSIENT_MAXLEN)
            ).append(item)
            self.__transient_total[address] = self.__transient_total.get(address, 0) + 1
        self.__bump()

    def transient(self, address):
        """瞬态地址的当前内容（快照）。"""
        with self.__transient_lock:
            return list(self.__transient.get(address, []))

    def transient_total(self, address):
        """该地址累计写入过多少条（含被容量挤掉的）。

        显示体系的游标要按**绝对计数**推进：deque 满了以后 len() 恒等于上限，
        只看 len 会把“后面的新片段”误判成“已经画过”。
        """
        with self.__transient_lock:
            return self.__transient_total.get(address, 0)

    def transient_window(self, address):
        """(内容快照, 绝对计数) —— 同一把锁里取，两个数必须对得上。"""
        with self.__transient_lock:
            return (
                list(self.__transient.get(address, [])),
                self.__transient_total.get(address, 0),
            )

    def clear_transient(self, address=None):
        """清空瞬态地址（轮末 / 新会话）。"""
        with self.__transient_lock:
            if address is None:
                self.__transient.clear()
                self.__transient_total.clear()
            else:
                self.__transient.pop(address, None)
                self.__transient_total.pop(address, None)
        self.__bump()

    # ---------- 等新数据 ----------
    def revision(self):
        """数据版本号：任何一次写入（持久 / 瞬态）都会 +1。"""
        with self.__data_cond:
            return self.__revision

    def wait_revision(self, seen, timeout=1.0):
        """等到版本号变化（或超时）；返回当前版本号。"""
        with self.__data_cond:
            if self.__revision == seen:
                self.__data_cond.wait(timeout)
            return self.__revision

    def __bump(self):
        with self.__data_cond:
            self.__revision += 1
            self.__data_cond.notify_all()

    def stats(self):
        """每种虚拟地址有多少条。"""
        self.flush()
        counts = {}
        for record in self.records():
            counts[record.address] = counts.get(record.address, 0) + 1
        return counts

    def clear(self):
        """清空（新会话）。建议先 flush()，别让在途的写入漏进来。"""
        with self.__lock:
            self.__seq = 0
            self.__floor = 0
            self.__records.clear()
            self.__views.clear()
            self.__last.clear()
        with self.__transient_lock:
            self.__transient.clear()
        self.__bump()

    # ---------- worker ----------
    def __loop(self):
        while True:
            item = self.__queue.get()
            if item is None:
                self.__queue.task_done()
                return
            ticket, address, payload = item
            try:
                self.__write(address, payload)
            except Exception as error:   # worker 不能因为一条坏记录死掉
                log.error("Memory", f"worker write failed: {type(error).__name__}: {error}")
            with self.__cond:
                self.__processed = ticket
                self.__cond.notify_all()
            self.__queue.task_done()

    def __write(self, address, payload):
        with self.__lock:
            self.__seq += 1
            record = Record(self.__seq, address, payload, turn.current())
            self.__records.append(record)
            self.__views.setdefault(address, []).append(record)
            self.__last[address] = record.seq
        self.__bump()
        return record


# 内存对象，多体系共用。
# 默认实例给 CLI / 单会话；多会话线程用 use(memory) 绑定自己的 Memory。
_DEFAULT = Memory()
_CURRENT = contextvars.ContextVar("spirit_memory", default=None)


class _MemoryProxy:
    """按当前线程/任务上下文解析到对应会话的 Memory。"""

    __slots__ = ()

    def __getattr__(self, name):
        target = _CURRENT.get() or _DEFAULT
        return getattr(target, name)

    def __setattr__(self, name, value):
        # 测试 / 诊断会临时替换 mem 的方法；写回当前会话的 Memory
        target = _CURRENT.get() or _DEFAULT
        setattr(target, name, value)

    def __delattr__(self, name):
        target = _CURRENT.get() or _DEFAULT
        delattr(target, name)


mem = _MemoryProxy()


def use(memory):
    return _CURRENT.set(memory)


def unuse(token):
    _CURRENT.reset(token)
