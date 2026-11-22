"""批 G：Web Host/令牌边界、Memory flush 竞态、沙箱兄弟文件、SSE 上限、shell 缓冲上限、打包覆盖。"""
import fnmatch
import os
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Capabilities.Sandbox import SandboxDenied, sandbox  # noqa: E402
from Capabilities.Shell import shell  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import mem  # noqa: E402
from WebUI import Output as web_out  # noqa: E402
from WebUI import server as web  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-bd-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-bd-work-"))
engine = Engine(home=home, workdir=work)
web._engine = engine

# ---------- 1. Web：Host 覆盖所有路由，查询参数不再当令牌 ----------
client = web.test_client()
assert client.get("/").status_code == 200
assert 'name="spirit-api-token"' in client.get("/").get_data(as_text=True)
assert client.get("/", base_url="http://evil.example").status_code == 403

raw = web.app.test_client()
raw.environ_base["HTTP_HOST"] = "127.0.0.1"
assert raw.get(f"/api/providers?token={web.API_TOKEN}").status_code == 401, "状态接口不该接受查询参数令牌"
assert raw.get("/api/events?token=" + web.API_TOKEN).status_code in (200, 401)  # SSE 例外（不实际读流）
assert client.get("/api/providers", headers={"Origin": "http://evil.example"}).status_code == 403
assert client.get("/api/providers", headers={"Origin": "http://127.0.0.1:5000"}).status_code == 200
print("1. Web 边界 ok")

# ---------- 2. Memory：ticket 与入队同锁，高并发 flush 不提前 ----------
mem.clear()
errors = []


def produce(worker):
    try:
        for index in range(200):
            mem.submit("user", f"w{worker}-{index}")
            if index % 20 == 0:
                mem.flush()
    except Exception as error:
        errors.append(error)


threads = [threading.Thread(target=produce, args=(i,)) for i in range(8)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
mem.flush()
assert not errors, errors
records = mem.records()
assert len(records) == 1600, len(records)
seqs = [record.seq for record in records]
assert seqs == list(range(1, 1601)), "seq 必须连续"
source = Path(root, "Memory", "Memory.py").read_text(encoding="utf-8")
assert "self.__submitted += 1" in source
assert source.index("self.__queue.put") < source.index("return ticket")
# 入队必须在 with self.__cond 的同一块里（用缩进粗判）
block = source[source.index("def submit"):source.index("def flush")]
assert block.index("self.__queue.put") < block.index("return ticket")
assert all(line.startswith("        ") or not line.strip() for line in block.splitlines() if "queue.put" in line)
print("2. Memory 并发 ok")

# ---------- 3. 沙箱保护配置的兄弟文件 ----------
config_bak = home / "config.json.bak"
config_bak.write_text('{"llm": {"api_key": "sk-test"}}', encoding="utf-8")
try:
    sandbox.resolve(str(work), str(config_bak))
    raise AssertionError("config.json.bak 应该被拒绝")
except SandboxDenied:
    pass
corrupt = home / "config.json.corrupt-20260101-000000"
corrupt.write_text("{}", encoding="utf-8")
try:
    sandbox.resolve(str(work), str(corrupt))
    raise AssertionError("corrupt 备份应该被拒绝")
except SandboxDenied:
    pass
print("3. 沙箱兄弟文件 ok")

# ---------- 4. SSE 队列有上限 ----------
subscriber = web_out.subscribe()
try:
    for index in range(2100):
        web_out.publish({"n": index})
    assert subscriber.qsize() == 2000, subscriber.qsize()
    first = subscriber.get_nowait()
    assert first["n"] == 100, first   # 丢的是最旧的
finally:
    web_out.unsubscribe(subscriber)
print("4. SSE 上限 ok")

# ---------- 5. 持久 shell 缓冲有上限 ----------
python = sys.executable.replace("\\", "/")
command = f'"{python}" -c "import sys; sys.stdout.write(\'x\'*3000000)"'
output, _status, problem = shell.run(
    str(work),
    sandbox.bash_env(str(work)),
    command,
    timeout=40,
)
shell.stop()
assert problem == "", problem
assert "输出过大" in output, output[:120]
assert len(output) < 2_600_000, len(output)
print("5. shell 缓冲上限 ok")

# ---------- 6. 打包覆盖每个包目录（Turn 曾经漏掉） ----------
data = tomllib.loads(Path(root, "pyproject.toml").read_text(encoding="utf-8"))
patterns = data["tool"]["setuptools"]["packages"]["find"]["include"]
excluded = data["tool"]["setuptools"]["packages"]["find"].get("exclude", [])
missing = []
for directory in Path(root).iterdir():
    if not directory.is_dir() or not (directory / "__init__.py").exists():
        continue
    name = directory.name
    if name.startswith(".") or name in {"build", "dist", "shell"}:
        continue
    if any(fnmatch.fnmatch(name + "/x", pattern) for pattern in excluded):
        continue
    if not any(fnmatch.fnmatch(name + "/x", pattern) for pattern in patterns):
        missing.append(name)
assert not missing, f"pyproject 漏了包：{missing}"
assert "Turn*" in patterns
print("6. 打包覆盖 ok")

print("ALL BOUNDARY TESTS PASSED")
