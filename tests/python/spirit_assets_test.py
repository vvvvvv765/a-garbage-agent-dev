"""资产测绘：平台配置 / FOFA 适配 / 项目资产库 / API / 清理。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-assets-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-assets-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities import Assets, AssetPlatforms  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from Render import render  # noqa: E402

render.set_console(False)
engine = Engine(home=home, workdir=work)
engine.use_scenario("pentest")
assert engine.start()

# ---------- 1. 平台配置 / 未配置时不可用 ----------
config.set("assets.platforms.fofa.enabled", True)
config.set("assets.platforms.fofa.key", "test-key")
assert AssetPlatforms.configured("fofa")
state = AssetPlatforms.platforms()
fofa = [item for item in state if item["id"] == "fofa"][0]
assert fofa["configured"] and "key" not in fofa, fofa
assert not AssetPlatforms.configured("quake")
print("1. 平台配置 ok")

# ---------- 2. FOFA 查询（mock 网络）→ 项目资产库 ----------
def fake_request(url, data=None, headers=None, timeout=25):
    assert "qbase64" in url and "test-key" in url
    return {
        "error": False, "total": 1,
        "results": [{
            "host": "https://a.example.com", "ip": "1.2.3.4", "port": "443",
            "domain": "a.example.com", "title": "Example Admin",
            "server": "nginx", "protocol": "https",
        }],
    }

AssetPlatforms._request = fake_request
raw = json.dumps({"query": 'domain="example.com"', "size": 20})
out = capabilities.run([CapabilityInput("a1", "fofaSearch", raw, json.loads(raw))])[0]
assert out.ok and "新增 1" in out.content, out.content
summary = Assets.summary("primary")
assert summary["total"] == 1, summary
rows = Assets.list_assets("primary")
assert rows[0]["domain"] == "a.example.com" and rows[0]["port"] == 443, rows
assert rows[0]["sources"] == ["fofa"], rows
assert Assets.queries("primary"), Assets.queries("primary")
csv_file = home / "Projects" / "primary" / "assets.csv"
assert csv_file.exists() and "域名" in csv_file.read_text(encoding="utf-8-sig")
assert not (home / "Projects" / "primary" / "domain.csv").exists()
print("2. FOFA → 资产库 + 总表 ok:", out.content.splitlines()[0])

# ---------- 2b. 总表双方都能写：模型加的列 / 行在引擎同步后保留 ----------
import csv as _csv  # noqa: E402

with open(csv_file, encoding="utf-8-sig", newline="") as _f:
    _reader = _csv.DictReader(_f)
    _header = list(_reader.fieldnames or [])
    _rows = [dict(row) for row in _reader]
_header += ["学号", "姓名"]
_rows.append({**{name: "" for name in _header}, "类型": "学生", "学号": "001", "姓名": "张三"})
with open(csv_file, "w", encoding="utf-8-sig", newline="") as _f:
    _writer = _csv.DictWriter(_f, fieldnames=_header)
    _writer.writeheader()
    _writer.writerows(_rows)
Assets.add_assets("primary", [{"domain": "c.example.com"}], source="subfinder")
_text = csv_file.read_text(encoding="utf-8-sig")
assert "学号" in _text and "张三" in _text and "c.example.com" in _text, _text
assert "a.example.com" in _text, _text
print("2b. 总表双方写入（模型加列加行保留）ok")

# ---------- 2c. assetsWrite：模型整理后写回资产库 ----------
from Capabilities.ProjectAssets import AssetsWriteCapability  # noqa: E402

written = AssetsWriteCapability().run({
    "records": [{"domain": "d.example.com", "port": "8443", "title": "D 面板"},
                {"ip": "10.0.0.9", "port": 22, "note": "课堂"}],
    "source": "整理",
})
assert "新增 2" in written.content, written.content
_assets = Assets.list_assets("primary")
assert any(r.get("domain") == "d.example.com" and r.get("port") == 8443 for r in _assets), _assets
assert "d.example.com" in csv_file.read_text(encoding="utf-8-sig")
print("2c. assetsWrite 整理写回 ok")

# ---------- 3. Web API ----------
from WebUI import server as web  # noqa: E402

web._engine = engine
http = web.test_client()
payload = http.get("/api/assets?session=primary").get_json()
assert payload["ok"] and payload["summary"]["total"] >= 1, payload
assert payload["queries"], payload
imported = http.post("/api/assets/csv/import", json={
    "session": "primary", "name": "students.csv",
    "text": "学号,姓名\n001,张三\n",
}).get_json()
assert imported["ok"] and "整理" in imported["hint"], imported
csvs = http.get("/api/assets/csvs?session=primary").get_json()
assert csvs["ok"] and any(item["name"] == "students.csv" for item in csvs["files"]), csvs
view = http.get("/api/assets/csv/view?session=primary&name=students.csv").get_json()
assert view["ok"] and view["columns"] == ["学号", "姓名"] and view["rows"][0] == ["001", "张三"], view
projects = http.get("/api/assets/projects?session=primary").get_json()
assert projects["ok"] and any(p["session"] == "primary" for p in projects["projects"]), projects
csv = http.get("/api/assets/csv?session=primary")
assert csv.status_code == 200 and "域名" in csv.get_data(as_text=True), csv.status_code
platforms = http.get("/api/assets/platforms").get_json()
assert platforms["ok"] and len(platforms["platforms"]) == 3, platforms
saved = http.post("/api/assets/platforms", json={
    "platform": "quake", "enabled": True, "key": "q-key",
}).get_json()
assert saved["ok"] and saved["platform"]["configured"], saved
print("3. 资产 API ok")

# ---------- 4. 项目隔离 / 清理 ----------
Assets.add_assets("other-project", [{"domain": "b.example.com"}], source="subfinder")
assert Assets.summary("primary")["total"] > 0
assert Assets.summary("other-project")["total"] == 1
removed = http.post("/api/assets/clear", json={"session": "primary"}).get_json()
assert removed["ok"] and removed["removed"] >= 1, removed
assert Assets.summary("primary")["total"] == 0
assert Assets.summary("other-project")["total"] == 1
print("4. 项目隔离与清理 ok")

# ---------- 5. 外部工具路径 ----------
from Capabilities.Tools import tool_path  # noqa: E402

for name in ("ffuf", "subfinder", "naabu"):
    assert tool_path(name) is not None, f"{name} 未找到"
print("5. 外部工具路径 ok")

# ---------- 6. 硬盘 projects 区域 ----------
assert "projects" in engine.disk_info()["areas"]
removed = engine.disk_clear("projects")
assert removed >= 1
assert not any((home / "Projects").rglob("assets.json"))
print("6. 硬盘项目区清理 ok")

engine.stop()
render.shutdown()
print("\nALL ASSETS TESTS PASSED")
