"""真实 ego lite 浏览器冒烟（需要已安装并完成 onboarding；离线回归会跳过 live）。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-browser-live-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-browser-live-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities import Browser as browser_module  # noqa: E402
from Capabilities.Browser import find_browser  # noqa: E402
from Config import config  # noqa: E402
from Paths import home as data_home  # noqa: E402

exe = find_browser()
assert exe is not None, "没装 ego lite"
config.set("engine.ego_browser", str(exe))

shot = work / "live-shot.png"
code = f"""
const task = await spiritTask();
const page = task.page("p1");
await page.goto("https://example.com", {{ timeout: 30000 }});
await spiritShot(page, {{ path: {json.dumps(str(shot))} }});
console.log("TITLE:" + await page.title());
console.log("PAGES:" + (await task.pages()).length);
"""
raw = json.dumps({"code": code, "timeout": 90})
out = capabilities.run([CapabilityInput("live", "browser", raw, json.loads(raw))])[0]
assert out.ok, out.content
assert "TITLE:Example Domain" in out.content, out.content[:400]
images = (out.meta or {}).get("images") or []
assert len(images) == 1, images
assert shot.exists() and shot.stat().st_size > 1000, shot
assert (data_home() / "uploads" / images[0]["id"]).exists()
print("1. 真实浏览器 + 截图 ok:", out.content.splitlines()[0])

# 第二次调用：spiritTask() 应复用同一个 Space，页面还在
code2 = """
const task = await spiritTask();
console.log("SPACE:" + task.spaceId);
console.log("PAGES:" + (await task.pages()).length);
"""
raw = json.dumps({"code": code2, "timeout": 60})
out = capabilities.run([CapabilityInput("live2", "browser", raw, json.loads(raw))])[0]
assert out.ok and "PAGES:" in out.content, out.content
assert "SPACE:" in out.content, out.content
print("2. Space 复用 ok:", out.content.replace("\n", " | "))

# 3. 观察快照：当前 Space / 页面 / 最近截图
snapshot = browser_module.status("primary")
assert snapshot["installed"] and snapshot["onboarded"] is True, snapshot
assert snapshot["space"] and snapshot["space"].get("title") == "Example Domain", snapshot
assert snapshot["last_screenshot"]["path"] == str(shot), snapshot
print("3. 观察快照 ok:", snapshot["space"])

# 4. 开机补清理只动旧 Space；关机释放 Space
assert browser_module.cleanup_stale_spaces() == 0, "刚创建的 Space 不该被开机清理"
released = browser_module.release_spaces()
assert released >= 1, released
after = browser_module.status("primary")
assert not (after.get("space") or {}).get("space"), after
print("4. 释放 Space ok:", released)

# 5. 强杀补清理：旧 Space 文件在开机清理时被释放，新文件不动
script = 'const t = await taskSpace("spirit-stale-cleanup"); console.log("ID:" + t.spaceId);'
result = browser_module._quick(exe, ["nodejs"], script, 30)
text = (result.stdout or b"").decode("utf-8", errors="replace")
assert "ID:" in text, text
space_id = text.split("ID:", 1)[1].split()[0].strip()
space_dir = data_home() / "browser"
space_dir.mkdir(parents=True, exist_ok=True)
stale = space_dir / "spirit-stale-cleanup.space"
stale.write_text(space_id, encoding="utf-8")
old = os.path.getmtime(stale) - 120
os.utime(stale, (old, old))
assert browser_module.cleanup_stale_spaces() >= 1, "旧的 Space 没有被清理"
assert not stale.exists()
print("5. 强杀后开机补清理 ok")

print("\nBROWSER LIVE TEST OK")
