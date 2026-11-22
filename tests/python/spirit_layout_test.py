"""引擎实例路径测试：Engine(home=..., workdir=...) 能否决定数据根 / 工作区。

覆盖：
  - 数据根切换（会话 / 日志 / spill / 审计）
  - 工作目录切换（文件能力相对路径 + bash cwd）
  - 每个实例自己的 config.json
  - 环境变量 SPIRIT_HOME 仍然可用（子进程模式）
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ.pop("SPIRIT_HOME", None)
os.environ.pop("SPIRIT_SESSION_DIR", None)
os.environ.pop("SPIRIT_LOG_DIR", None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
from Log import log  # noqa: E402
from Memory import mem  # noqa: E402
from Memory.Persist import persist  # noqa: E402
from Paths import log_dir, session_dir, spill_dir  # noqa: E402


def call(name, arguments):
    raw = json.dumps(arguments, ensure_ascii=False)
    output = capabilities.run([CapabilityInput("c-" + name, name, raw, arguments)])[0]
    assert output.ok, output.content
    return output.content


def make(prefix):
    return Path(tempfile.mkdtemp(prefix=prefix))


# ---------- 实例 A：home + workdir 都由构造参数决定 ----------
home_a, work_a = make("spirit-homeA-"), make("spirit-workA-")
(home_a / "config.json").write_text(json.dumps({
    "llm": {"model": "model-A"},
    "engine": {"thinking": True, "max_steps": 5},
}), encoding="utf-8")
(work_a / "marker.txt").write_text("from A", encoding="utf-8")

engine_a = Engine(home=home_a, workdir=work_a)
assert Path(engine_a.home) == home_a.resolve(), engine_a.home
assert Path(engine_a.workdir) == work_a.resolve(), engine_a.workdir
assert config.get("llm.model") == "model-A"
assert config.get("engine.max_steps") == 5
assert engine_a.settings()["thinking"] is True
assert session_dir() == home_a / "Session_Storage", session_dir()
assert log_dir() == home_a / "Logs", log_dir()
assert spill_dir("Session_Storage/spill") == home_a / "Session_Storage/spill"
print("home A ok:", engine_a.home)
print("workdir A ok:", engine_a.workdir)

assert "from A" in call("readFile", {"path": "marker.txt"})
assert "spirit-worka" in call("bash", {"bashinput": "pwd"}).lower()
log.info("Test", "log in A")
assert (home_a / "Logs" / "spirit.log").exists()
print("workdir A reached file + bash capabilities")

security.set_approver(lambda request: True)
security.check("readFile", "{}", "call-a")
assert (home_a / "Logs" / "audit.jsonl").exists()

mem.submit("user", "A 的会话")
mem.flush()
saved = persist.save()
assert saved and Path(saved).parent == home_a / "Session_Storage", saved
print("session A ok:", Path(saved).name)

# ---------- 实例 B：workdir 来自 B 自己的 config ----------
home_b, work_b = make("spirit-homeB-"), make("spirit-workB-")
(home_b / "config.json").write_text(json.dumps({
    "engine": {"workdir": str(work_b), "max_steps": 9},
}), encoding="utf-8")
(work_b / "marker.txt").write_text("from B", encoding="utf-8")

engine_b = Engine(home=home_b)
assert Path(engine_b.home) == home_b.resolve()
assert Path(engine_b.workdir) == work_b.resolve(), engine_b.workdir
assert config.get("engine.max_steps") == 9
assert session_dir() == home_b / "Session_Storage"
assert "from B" in call("readFile", {"path": "marker.txt"})
log.info("Test", "log in B")
assert (home_b / "Logs" / "spirit.log").exists()
print("home B + config workdir ok:", engine_b.workdir)

# ---------- 子进程模式：环境变量仍然优先于默认规则 ----------
home_c = make("spirit-homeC-")
os.environ["SPIRIT_HOME"] = str(home_c)
try:
    engine_c = Engine()
    assert Path(engine_c.home) == home_c.resolve(), engine_c.home
    assert Path(engine_c.workdir) == Path(engine_c.home) / "workspace", engine_c.workdir
    assert Path(engine_c.workdir).is_dir(), engine_c.workdir
    print("SPIRIT_HOME env ok:", engine_c.home)
finally:
    os.environ.pop("SPIRIT_HOME", None)

print("\nLAYOUT TEST OK")
