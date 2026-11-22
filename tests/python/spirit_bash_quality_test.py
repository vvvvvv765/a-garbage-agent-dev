"""bash 结果质量：非零退出码必须回给模型，不能当成成功。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-bashq-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-bashq-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402
from Render import render  # noqa: E402

render.set_console(False)
engine = Engine(home=home, workdir=work)
engine.start()


def run(command):
    return capabilities.run([CapabilityInput(
        "c", "bash", json.dumps({"command": command}), {"command": command},
    )])[0]


result = run("echo before; (exit 3)")
assert result.ok, result
assert "before" in result.content and "[exit 3]" in result.content, result.content
print("1. bash non-zero exit visible ok")

result = run("false")
assert "[exit 1]" in result.content, result.content
print("2. silent failure visible ok")

result = run("true")
assert "[exit" not in result.content, result.content
print("3. success stays clean ok")

render.shutdown()
print("\nBASH QUALITY TEST OK")
