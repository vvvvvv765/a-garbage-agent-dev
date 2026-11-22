"""sandboxRun 能力：一次性隔离环境（WSL + bwrap）。

验证：默认不再限制工作区；来源不明的命令放进沙箱后看不到宿主、默认断网。
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-sbox-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-sbox-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-sbox-work-"))
outside = Path(tempfile.mkdtemp(prefix="spirit-sbox-out-"))
(outside / "secret.txt").write_text("secret", encoding="utf-8")
engine = Engine(home=home, workdir=work)
engine.use_scenario("pentest")  # sandboxRun 只在渗透场景
engine.set_approval("auto")

# ---------- 1. 默认不再限制工作区；机器数据仍拒绝 ----------
ok, reason = capabilities.precheck("readFile", {"path": str(outside / "secret.txt")})
assert ok is True, reason
ok, reason = capabilities.precheck("readFile", {"path": str(Path(home) / "config.json")})
assert ok is False and "沙箱拒绝" in reason, reason
print("1. 默认无工作区边界 ok")

# ---------- 2. 能力已注册 ----------
names = {item["name"] for item in capabilities.schemas()}
assert "sandboxRun" in names, sorted(names)
print("2. sandboxRun 已注册 ok")

if not (shutil.which("wsl") or Path(r"C:\Windows\System32\wsl.exe").exists()):
    print("SKIP: 没有 WSL")
    raise SystemExit(0)

# ---------- 3. 隔离环境：能跑、能写 /work、看不到 /mnt ----------
raw = json.dumps({"command": "echo HELLO; pwd; ls /mnt 2>&1 | head -1; echo x > note.txt; ls"}, ensure_ascii=False)
out = capabilities.run([CapabilityInput("c-sbox", "sandboxRun", raw, json.loads(raw))])[0]
text = out.content
assert out.ok, text
assert "HELLO" in text, text
assert "/work" in text, text
assert "No such file" in text or "无法访问" in text, text
assert "note.txt" in text, text
assert "退出码 0" in text, text
print("3. 隔离执行 ok")

# ---------- 4. 默认断网 ----------
raw = json.dumps({
    "command": "python3 -c \"import socket; print(socket.gethostbyname('example.com'))\"",
}, ensure_ascii=False)
out = capabilities.run([CapabilityInput("c-net", "sandboxRun", raw, json.loads(raw))])[0]
assert "退出码 0" not in out.content, out.content
print("4. 默认断网 ok")

# ---------- 5. 每次调用独立工作目录，宿主可检查 ----------
root = Path(home) / "Sandbox"
notes = list(root.glob("*/note.txt"))
assert notes, list(root.iterdir())
assert notes[0].read_text(encoding="utf-8").strip() == "x"
assert len({path.parent.name for path in notes}) >= 1
print("5. 沙箱独立工作目录 ok")

# ---------- 6. 取消：不等超时 ----------
import threading
import time

from Cancel import token as cancel_token
from Capabilities.IsolatedRun import IsolatedRunCapability

cancel_token.clear()
holder = {}
cap = IsolatedRunCapability()


def run_sleep():
    started = time.time()
    holder["out"] = cap.run({"command": "sleep 20", "timeout": 60})
    holder["elapsed"] = time.time() - started


thread = threading.Thread(target=run_sleep)
thread.start()
time.sleep(1.0)
cancel_token.set()
thread.join(10)
cancel_token.clear()
assert not thread.is_alive(), "取消后 sandboxRun 没有返回"
assert "已取消" in holder["out"], holder["out"]
assert holder["elapsed"] < 8, holder["elapsed"]
print("6. sandboxRun 取消 ok:", round(holder["elapsed"], 1), "s")

print("\nALL SANDBOX RUN TESTS PASSED")
