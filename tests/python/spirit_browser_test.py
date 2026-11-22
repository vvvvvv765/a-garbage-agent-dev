"""browser 能力：ego-browser CLI 包装（用假 CLI 测路径 / 超时 / 图片 / 指南）。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-browser-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-browser-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402
from Paths import home as data_home  # noqa: E402

png = work / "shot.png"
png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

fake_py = work / "fake_ego.py"
fake_py.write_text(
    "import sys, time, json\n"
    "args = sys.argv[1:]\n"
    "if args and args[0] == 'skill':\n"
    "    print('[ego-browser:skill] FAKE GUIDE')\n"
    "    sys.exit(0)\n"
    "data = sys.stdin.read()\n"
    "if '__SPIRIT_READY__' in data:\n"
    "    print('__SPIRIT_READY__')\n"
    "    sys.exit(0)\n"
    "if 'PERMISSION' in data:\n"
    "    print('Error: A browser permission prompt for local network access has appeared.')\n"
    "    print('Resume using takeOverTaskSpace(spaceId).')\n"
    "    sys.exit(1)\n"
    "print('out:' + data.strip().splitlines()[-1][:60])\n"
    "if 'SLEEP' in data:\n"
    "    time.sleep(5)\n"
    f"print('__SPIRIT_IMAGES__' + json.dumps([{str(png)!r}]))\n",
    encoding="utf-8",
)
fake_cmd = work / "ego-browser.cmd"
fake_cmd.write_text(
    "@echo off\n"
    f'"{sys.executable}" "{fake_py}" %*\n',
    encoding="utf-8",
)


def run(arguments):
    raw = json.dumps(arguments, ensure_ascii=False)
    return capabilities.run([CapabilityInput("c", "browser", raw, arguments)])[0]


config.set("engine.ego_browser", str(fake_cmd))

# ---------- 1. 正常脚本 + 截图附件 ----------
out = run({"code": "console.log(1)"})
assert out.ok, out.content
assert "out:" in out.content and "__SPIRIT_IMAGES__" not in out.content, out.content
images = (out.meta or {}).get("images") or []
assert len(images) == 1 and images[0]["id"].endswith(".png"), images
assert (data_home() / "uploads" / images[0]["id"]).exists(), images
print("1. 脚本执行 + 截图进上下文 ok")

# ---------- 1b. 健康检查 / 观察快照 ----------
import time  # noqa: E402
from Capabilities import Browser as browser  # noqa: E402

deadline = time.monotonic() + 5
while time.monotonic() < deadline and browser.health().get("onboarded") is None:
    time.sleep(0.1)
snap = browser.health()
assert snap["installed"] and snap["onboarded"] is True, snap
state = browser.status("primary")
assert state["last_screenshot"]["path"] == str(png), state
print("1b. 健康检查 + 最近截图 ok")

# ---------- 1c. 权限交接：标记 + 等待用户，成功后清除 ----------
out = run({"code": "PERMISSION"})
assert not out.ok and "控制权" in out.content, out.content
handoff = data_home() / "browser" / "spirit-primary.handoff"
assert handoff.exists(), handoff
state = browser.status("primary")
assert state["attention"] == "permission", state
out = run({"code": "console.log(1)"})
assert out.ok, out.content
assert not handoff.exists(), "成功后应清除交接标记"
print("1c. 权限交接标记 ok")

# ---------- 2. guide ----------
guide = run({"guide": True})
assert guide.ok and "FAKE GUIDE" in guide.content, guide.content
print("2. guide ok")

# ---------- 3. 超时 ----------
out = run({"code": "SLEEP", "timeout": 1})
assert not out.ok and "超时" in out.content, out.content
print("3. timeout ok")

# ---------- 4. 缺 code / 缺 CLI ----------
out = run({})
assert "code 不能为空" in out.content, out.content
import Capabilities.Browser as browser_module  # noqa: E402

original_find = browser_module.find_browser
browser_module.find_browser = lambda: None
try:
    out = run({"code": "console.log(1)"})
    assert not out.ok and "没找到 ego-browser" in out.content, out.content
finally:
    browser_module.find_browser = original_find
print("4. 缺参数 / 缺 CLI 提示 ok")

# ---------- 5. 便携包自带 ego 的路径能被发现 ----------
bundled_root = Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")) / "shell" / "ego-lite"
bundled = next(
    (path for path in [bundled_root / "ego-browser.exe"]
     + [folder / "ego-browser.exe" for folder in bundled_root.iterdir() if folder.is_dir()]
     if path.exists()),
    None,
)
assert bundled is not None, bundled_root
original_candidates = browser_module._candidates
browser_module._candidates = lambda: iter([bundled])
try:
    assert browser_module.find_browser() == bundled
finally:
    browser_module._candidates = original_candidates
print("5. 便携自带 ego 路径 ok")

print("\nALL BROWSER TESTS PASSED")
