"""
进程级单实例锁：一个数据根只允许一个 Spirit 进程。

为什么放在入口而不是 Engine 构造：
  - Engine(home=...) 仍允许同进程里建多个实例（测试 / 嵌入用）
  - 真正危险的是**两个进程**同时写同一个 config / 会话
锁用 OS 文件锁持有：进程崩了自动释放，不会留死锁。
"""
import os
from pathlib import Path

try:                     # Windows
    import msvcrt
except ImportError:      # POSIX
    msvcrt = None
    import fcntl


class InstanceLock:
    def __init__(self, home=None):
        self.path = Path(home or os.getcwd()) / "spirit.lock"
        self.__handle = None

    def acquire(self):
        """拿锁；拿不到抛 RuntimeError（附持有者 PID）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = ""
            try:
                holder = self.path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                pass
            handle.close()
            raise RuntimeError(
                f"另一个 Spirit 进程正在使用数据根 {self.path.parent}"
                + (f"（PID {holder}）" if holder else "")
                + "；请先关掉它，或设置 SPIRIT_ALLOW_MULTI=1 强制多开"
            )
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        except OSError:
            pass
        self.__handle = handle
        return self

    def release(self):
        handle = self.__handle
        self.__handle = None
        if handle is None:
            return
        try:
            if msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            handle.close()
        except OSError:
            pass


# 必须留住引用：InstanceLock 一被回收，文件句柄就关了，锁也跟着释放
_HELD = None


def acquire_for_current_home():
    """按 Paths 的当前数据根拿锁；SPIRIT_ALLOW_MULTI=1 时跳过。"""
    global _HELD
    if str(os.environ.get("SPIRIT_ALLOW_MULTI", "")) in {"1", "true", "yes"}:
        return None
    if _HELD is not None:
        return _HELD
    from Paths import home
    _HELD = InstanceLock(home()).acquire()
    return _HELD
