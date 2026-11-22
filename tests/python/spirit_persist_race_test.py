"""并发 save()：同一批记录只能落一次（读水位 + 追加 + 更新水位是同一临界区）。"""
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = tempfile.mkdtemp(prefix="spirit-persist-race-")
os.environ["SPIRIT_SESSION_DIR"] = home
os.environ["SPIRIT_HOME"] = home

from Memory import mem  # noqa: E402
from Memory.Persist import PersistSystem  # noqa: E402

for i in range(30):
    mem.submit("user", f"m{i}")
mem.flush()

persist = PersistSystem()
threads = [
    threading.Thread(target=lambda: [persist.save() for _ in range(20)])
    for _ in range(6)
]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()

files = sorted(f for f in os.listdir(home) if f.startswith("session-") and f.endswith(".jsonl"))
assert len(files) == 1, f"并发首存撞出了多个会话文件：{files}"
path = os.path.join(home, files[0])
lines = [line for line in open(path, encoding="utf-8") if line.strip()]
print("记录 30 条；落盘行数 =", len(lines), "；会话文件数 =", len(files))
assert len(lines) == 30, f"重复落盘：{len(lines)} 行"

records = {}
for line in lines:
    import json
    item = json.loads(line)
    records[item["payload"]] = records.get(item["payload"], 0) + 1
assert all(count == 1 for count in records.values()), records

# 重新加载：内存记录条数应与写出一致（不再翻倍）
mem.clear()
restored = PersistSystem()
restored.load(path)
assert len(mem.records()) == 30, len(mem.records())
print("reload ok:", len(mem.records()), "records")

print("\nPERSIST RACE TEST OK")
