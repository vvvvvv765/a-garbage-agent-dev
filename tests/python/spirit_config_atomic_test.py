"""配置并发与原子写测试：多线程 set/save 不炸；半截写不覆盖原文件。"""
import json
import os
import sys
import tempfile
import threading
import time
import traceback

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_HOME"] = tempfile.mkdtemp(prefix="spirit-config-home-")
for name in ("SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

import Config.core as core  # noqa: E402
from Config import config  # noqa: E402
from Paths import config_file  # noqa: E402

config.load()
target = config_file()
config.set("engine.approval", "manual")
config.save()
assert target.exists(), target


def temp_files():
    return [p.name for p in target.parent.glob(".*.tmp")]


# ---------- 1. 并发 set + save：不抛异常，文件始终是合法 JSON ----------
errors = []
stop = threading.Event()


def writer(index):
    try:
        for step in range(40):
            config.set("engine.approval", ["rules", "manual", "auto"][step % 3])
            config.set(f"engine.probe_{index}", step)
            config.save()
    except Exception as error:   # noqa: BLE001
        errors.append((error, traceback.format_exc()))


def reader():
    try:
        while not stop.is_set():
            config.get("engine.approval")
            try:
                json.loads(target.read_text(encoding="utf-8"))
            except PermissionError:
                pass   # Windows：正好撞上 os.replace 的瞬间，重试即可
            time.sleep(0.002)   # 别一直攥着文件：Windows 上会卡住 os.replace
    except Exception as error:   # noqa: BLE001
        errors.append(("reader", error))


threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
watch = threading.Thread(target=reader, daemon=True)
watch.start()
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
stop.set()
watch.join(timeout=2)

assert not errors, errors
data = json.loads(target.read_text(encoding="utf-8"))
assert "engine" in data and "llm" in data
assert not temp_files(), temp_files()
print("concurrent set/save ok")

# ---------- 2. 写一半崩：原文件保持完整，临时文件清掉 ----------
baseline = target.read_text(encoding="utf-8")
original_dump = core.json.dump


def broken_dump(obj, fp, **kwargs):
    fp.write('{"engine": {')     # 只写半截
    raise RuntimeError("模拟写到一半崩溃")


core.json.dump = broken_dump
try:
    try:
        config.save()
        raise AssertionError("save 应该把异常抛出来")
    except RuntimeError as error:
        assert "模拟" in str(error), error
finally:
    core.json.dump = original_dump

assert target.read_text(encoding="utf-8") == baseline, "半截写覆盖了原配置"
assert not temp_files(), temp_files()
print("atomic replace ok")

print("ALL CONFIG ATOMIC TESTS PASSED")
