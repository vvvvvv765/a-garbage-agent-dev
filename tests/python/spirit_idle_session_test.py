"""空闲（等用户输入）时也必须能新建 / 切会话。"""
import os
import queue
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-idle-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-idle-work-"))
os.environ["SPIRIT_HOME"] = str(home)
for name in ("SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Engine import Engine  # noqa: E402

engine = Engine(home=home, workdir=work)
messages = queue.Queue()
waiting = threading.Event()


def source():
    waiting.set()
    value = messages.get()
    if value is None:
        raise EOFError
    return value


engine.set_input_source(source)
assert engine.start()
thread = threading.Thread(target=engine.run, name="idle-cpu", daemon=True)
thread.start()
assert waiting.wait(5), "CPU 没有进入等输入状态"

# CPU 正阻塞在输入源上（没有 turn_active），新建会话必须成功
assert engine.new_session() == []
print("1. 空闲新会话 ok")

# 切到一份历史会话也要能成功
session = home / "Session_Storage" / "session-20260101-000000.jsonl"
session.parent.mkdir(parents=True, exist_ok=True)
session.write_text(
    '{"seq": 1, "address": "user", "payload": "旧问题"}\n'
    '{"seq": 2, "address": "assistant", "payload": "旧回答"}\n',
    encoding="utf-8",
)
events = engine.load_session(str(session))
assert [item["type"] for item in events] == ["user_message", "assistant_message"], events
print("2. 空闲切会话 ok")

# 关掉 CPU，确认锁已释放且线程正常退出
assert engine.new_session() == []
messages.put(None)
thread.join(10)
assert not thread.is_alive(), "CPU 没有正常退出"
print("3. 锁交接与关机 ok")

print("\nIDLE SESSION TEST PASSED")
