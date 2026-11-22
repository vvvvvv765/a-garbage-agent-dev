"""
用户输入体系：读入用户输入，写内存，向 CPU 报告
"""
from Contract import Contract
from Bus import NT, keys
from Memory import mem, USER
from Faults import faults

_faults = faults.for_system("UserInput")


class User:
    def __init__(self, memory=None, bus=None):
        self.__mem = memory if memory is not None else mem
        self.__nt = bus if bus is not None else NT
        self.intext = ""
        self.__source = None
        self.__session_lock = None
        self.__session_held = False

    def set_source(self, source):
        """换输入源（Web UI 用队列；默认是控制台 input）。"""
        self.__source = source

    # ---------- 会话锁交接 ----------
    # 阻塞等用户输入时不能占着会话锁，否则新建 / 切会话永远 409。
    # 输入真正到了才拿锁，并一直拿到本轮处理完（由 CPU 在轮末释放）。
    def session_lock_held(self):
        return self.__session_held

    def release_session_lock(self):
        lock = self.__session_lock
        self.__session_lock = None
        if lock is None:
            return
        if self.__session_held:
            self.__session_held = False
            lock.release()

    def __read(self):
        if self.__source is not None:
            return self.__source()
        return input("用户输入：")

    def uim(self):
        """读一次用户输入；异常交给本体系的异常处理。"""
        try:
            self.__uim()
        except Exception as error:
            self.release_session_lock()
            _faults.report(error, "uim")
            self.__nt.register(keys.USER_INPUT, Contract(start=False, SI=False, skip=True))

    def __uim(self):
        start = True
        si = False
        skip = False

        ctrl = self.__nt.get(keys.CPU_USER)
        if ctrl is None or not ctrl.should_process:
            skip = True
        else:
            self.intext = ""
            try:
                value = self.__read()
            except EOFError:
                start = False  # 关机
            else:
                if isinstance(value, dict):
                    text = str(value.get("text") or "").strip()
                    images = value.get("images") or []
                else:
                    text = str(value or "").strip()
                    images = []
                self.intext = text
                if text or images:
                    si = True
                    if text == "exit" and not images:
                        start = False
                    else:
                        lock = self.__nt.get(keys.SESSION_LOCK)
                        if lock is not None:
                            lock.acquire()
                            self.__session_lock = lock
                            self.__session_held = True
                        try:
                            self.__mem.submit(
                                USER,
                                {"text": text, "images": images} if images else text,
                            )
                        except BaseException:
                            self.release_session_lock()
                            raise
                else:
                    if self.__source is None:
                        print("输入为空")
                    skip = True

        self.__nt.register(keys.USER_INPUT, Contract(start=start, SI=si, skip=skip))


# 用户输入对象，多体系共用
userinput = User()
