"""硬盘体系：区域 / 落盘 / 使用量 / 清理 / API / 大输出自动落盘。"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-disk-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402
from Disk import disk  # noqa: E402
from Engine import Engine  # noqa: E402
from Paths import artifacts_dir  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-disk-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-disk-work-"))
engine = Engine(home=home, workdir=work)
engine.set_approval("auto")
assert engine.start()

# ---------- 1. 区域 ----------
info = engine.disk_info()
areas = info["areas"]
assert set(areas) == {"workspace", "artifacts", "sessions", "logs", "sandbox", "uploads", "projects"}, areas
assert Path(areas["workspace"]["path"]) == work.resolve()
assert Path(areas["artifacts"]["path"]) == artifacts_dir().resolve()
assert not str(areas["artifacts"]["path"]).startswith(str(work.resolve())), "能力产物区不能在工作区里"
assert Path(areas["sessions"]["path"]) == Path(engine.session_dir).resolve()
for row in areas.values():
    assert row["exists"], row
print("1. 硬盘区域 ok")

# ---------- 2. 落盘 / 使用量 ----------
written = disk.artifact("report", "a,b,c\n1,2,3\n", folder="collect")
path = Path(written["path"])
assert path.exists() and path.read_text(encoding="utf-8").startswith("a,b,c")
assert str(path).startswith(str(artifacts_dir()))
usage = disk.usage()["artifacts"]
assert usage["files"] >= 1 and usage["bytes"] >= written["bytes"]
print("2. 落盘与使用量 ok")

# ---------- 3. 各区域清理语义 ----------
removed = engine.disk_clear("artifacts")
assert removed >= 1
assert disk.usage()["artifacts"]["files"] == 0

# 会话：只清空文件，有内容的保留
sessions = Path(engine.session_dir)
(sessions / "session-empty.jsonl").write_bytes(b"")
(sessions / "session-empty.jsonl.meta.json").write_text("{}", encoding="utf-8")
(sessions / "session-keep.jsonl").write_text('{"seq":1}\n', encoding="utf-8")
removed = engine.disk_clear("sessions")
assert removed == 1
assert not (sessions / "session-empty.jsonl").exists()
assert (sessions / "session-keep.jsonl").exists()
(sessions / "session-keep.jsonl").unlink()

# 沙箱 / 工作区临时 / 日志
sandbox = disk.area("sandbox")
(sandbox / "x").mkdir(exist_ok=True)
(sandbox / "x" / "a.txt").write_text("a", encoding="utf-8")
assert engine.disk_clear("sandbox") >= 1
assert not (sandbox / "x").exists()

tmp = work / "tmp"
tmp.mkdir(exist_ok=True)
(tmp / "t.txt").write_text("t", encoding="utf-8")
(work / "keep.txt").write_text("keep", encoding="utf-8")
assert engine.disk_clear("workspace") >= 1
assert not (tmp / "t.txt").exists() and (work / "keep.txt").exists()

logs = disk.area("logs")
(logs / "probe.log").write_text("x" * 10, encoding="utf-8")
assert engine.disk_clear("logs") >= 1
assert (logs / "probe.log").exists() and (logs / "probe.log").stat().st_size == 0
print("3. 各区域清理语义 ok")

# ---------- 4. 大输出自动进硬盘 ----------
class BigCap:
    name = "big_output"
    description = "测试：大输出"
    parameters = {"type": "object", "properties": {}}

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters, side_effect="read")

    def run(self, arguments):
        return "X" * 20000


engine.register_capability(BigCap())
out = capabilities.run([CapabilityInput("c-big", "big_output", "{}", {})])[0]
assert out.ok and "已落盘" in out.content, out.content
spill_path = Path(out.meta.get("path") or "")
assert spill_path.exists(), spill_path
assert str(spill_path).startswith(str(artifacts_dir() / "spill")), spill_path
assert not str(spill_path).startswith(str(work.resolve())), "落盘产物不能写进工作区"
assert "大输出" not in out.content or len(out.content) < 5000

# 模型要能按 meta.path 读回全文（沙箱必须放行能力产物区）
read_back = capabilities.run([
    CapabilityInput("c-read", "readFile", json.dumps({"path": str(spill_path)}), {"path": str(spill_path)})
])[0]
assert read_back.ok and "XXXX" in read_back.content, read_back.content[:200]
print("4. 大输出落盘 + 按路径读回 ok")

# ---------- 5. Web API ----------
from WebUI import server as web  # noqa: E402

web._engine = engine
http = web.test_client()
payload = http.get("/api/disk").get_json()
assert payload["ok"] and "areas" in payload, payload
assert payload["roots"]["artifacts"].endswith("Artifacts")
res = http.post("/api/disk/clear", json={"area": "artifacts"}).get_json()
assert res["ok"], res
res = http.post("/api/disk/clear", json={"area": "logs"})
assert res.status_code == 200 and res.get_json()["ok"], res.get_json()
print("5. Web 接口 ok")

print("\nALL DISK TESTS PASSED")
