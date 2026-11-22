"""四类能力第二批：parseData / archiveCreate / archiveList / archiveExtract。"""
import gzip
import json
import os
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-data-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="spirit-data-work-"))
home = Path(tempfile.mkdtemp(prefix="spirit-data-home-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")
assert engine.start()


def call(name, **arguments):
    raw = json.dumps(arguments, ensure_ascii=False)
    return capabilities.run([CapabilityInput(f"c-{name}", name, raw, arguments)])[0]


# ---------- 1. CSV ----------
(work / "people.csv").write_text(
    "姓名,年龄,城市\n张三,18,成都\n李四,20,北京\n", encoding="utf-8"
)
out = call("parseData", file="people.csv")
assert out.ok and "2 行数据" in out.content and "姓名" in out.content, out.content
assert "张三" in out.content, out.content
print("1. CSV ok")

# ---------- 2. JSON + path ----------
data = {"code": 0, "data": {"items": [{"name": "a", "n": 1}, {"name": "b", "n": 2}]}}
(work / "nested.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
out = call("parseData", file="nested.json", path="data.items[0].name")
assert out.ok and "a" in out.content and "类型：string" in out.content, out.content
out = call("parseData", file="nested.json")
assert out.ok and "code" in out.content and "items" in out.content, out.content
print("2. JSON ok")

# ---------- 3. YAML / XML / inline ----------
out = call("parseData", text="name: spirit\nitems:\n  - a\n  - b\n", format="yaml")
assert out.ok and "spirit" in out.content, out.content
out = call("parseData", text="a: 1\n---\nb: 2\n", format="yaml")
assert out.ok and "2 个文档" in out.content, out.content
out = call("parseData", text='<root><item id="1">x</item></root>', format="xml")
assert out.ok and "root" in out.content and "item" in out.content, out.content
out = call("parseData", text='[{"x": 1}, {"x": 2}]', format="json")
assert out.ok and "数组" in out.content, out.content
print("3. YAML / XML / inline ok")

# ---------- 4. SQLite ----------
db = work / "test.db"
connection = sqlite3.connect(str(db))
connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
connection.executemany("INSERT INTO users (name) VALUES (?)", [("张三",), ("李四",)])
connection.commit()
connection.close()
out = call("parseData", file="test.db")
assert out.ok and "users" in out.content and "name" in out.content, out.content
out = call("parseData", file="test.db", query="SELECT * FROM users WHERE id > ?", params=[1])
assert out.ok and "李四" in out.content and "张三" not in out.content, out.content
out = call("parseData", file="test.db", query="DROP TABLE users")
assert "只允许查询" in out.content, out.content
print("4. SQLite ok")

# ---------- 5. 打包 / 列目录 / 解包 ----------
source = work / "src"
(source / "sub").mkdir(parents=True, exist_ok=True)
(source / "a.txt").write_text("A", encoding="utf-8")
(source / "sub" / "b.txt").write_text("BB", encoding="utf-8")

out = call("archiveCreate", dest="pkg.zip", sources=["src"])
assert out.ok and "打包完成" in out.content, out.content
assert (work / "pkg.zip").exists()
out = call("archiveList", file="pkg.zip")
assert out.ok and "src/a.txt" in out.content and "src/sub/b.txt" in out.content, out.content
out = call("archiveExtract", file="pkg.zip", dest="unzip")
assert out.ok and "2 个文件" in out.content, out.content
assert (work / "unzip" / "src" / "a.txt").read_text(encoding="utf-8") == "A"
assert (work / "unzip" / "src" / "sub" / "b.txt").read_text(encoding="utf-8") == "BB"
print("5. zip 打包 / 解包 ok")

out = call("archiveCreate", dest="pkg.tar.gz", sources=["src"])
assert out.ok, out.content
out = call("archiveList", file="pkg.tar.gz")
assert out.ok and "src/sub/b.txt" in out.content, out.content
out = call("archiveExtract", file="pkg.tar.gz", dest="untar")
assert out.ok and (work / "untar" / "src" / "sub" / "b.txt").read_text(encoding="utf-8") == "BB"
print("6. tar.gz ok")

# ---------- 6. 单文件 gz ----------
with gzip.open(work / "one.txt.gz", "wb") as stream:
    stream.write(b"gzip-content")
out = call("archiveList", file="one.txt.gz")
assert out.ok and "单文件" in out.content, out.content
out = call("archiveExtract", file="one.txt.gz", dest="gzout", output="restored.txt")
assert out.ok, out.content
assert (work / "gzout" / "restored.txt").read_bytes() == b"gzip-content"
print("7. 单文件 gz ok")

# ---------- 7. 恶意路径 / 覆盖开关 ----------
bad = work / "bad.zip"
with zipfile.ZipFile(bad, "w") as archive:
    archive.writestr("../escape.txt", b"x")
    archive.writestr("safe.txt", b"y")
out = call("archiveExtract", file="bad.zip", dest="badextract")
assert not out.ok or "失败" in out.content or ".." in out.content, out.content
assert not (work / "escape.txt").exists(), "路径穿越没有拦住"
print("8. 路径穿越拦截 ok")

(work / "over" / "src").mkdir(parents=True, exist_ok=True)
(work / "over" / "src" / "a.txt").write_text("OLD", encoding="utf-8")
out = call("archiveExtract", file="pkg.zip", dest="over", overwrite=False)
assert out.ok and "跳过" in out.content, out.content
assert (work / "over" / "src" / "a.txt").read_text(encoding="utf-8") == "OLD"
print("9. overwrite=false ok")

# ---------- 8. 进程隔离下 YAML / 解包也能跑 ----------
from Config import config  # noqa: E402

config.set("engine.capability_isolation", True)
out = call("parseData", text="name: worker\n", format="yaml")
assert out.ok and "worker" in out.content, out.content
out = call("archiveList", file="pkg.zip")
assert out.ok and "src/a.txt" in out.content, out.content
assert capabilities.stats()["worker"]["enabled"] is True, capabilities.stats()
print("10. worker 隔离 ok:", capabilities.stats()["worker"]["pids"])
capabilities.shutdown()
config.set("engine.capability_isolation", False)

capabilities.apply_scenario("daily")
print("\nALL DATA / ARCHIVE CAPABILITIES TESTS PASSED")
