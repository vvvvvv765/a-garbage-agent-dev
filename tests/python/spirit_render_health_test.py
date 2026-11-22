"""渲染运行期健康：异常不静默死线程，状态可见，恢复后 healthy 回来。"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from Engine import Engine  # noqa: E402
from Memory import mem  # noqa: E402
from Render.Render import Renderer  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-render-health-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-render-health-work-"))
engine = Engine(home=home, workdir=work)


def wait_until(predicate, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# Engine.status() 带 render 健康字段
status = engine.status()
assert "render" in status, status
assert {"alive", "healthy", "error"} <= set(status["render"]), status["render"]
print("engine status render ok")

renderer = Renderer()
renderer.start()
assert wait_until(lambda: renderer.status()["alive"]), renderer.status()

original = mem.records_after
try:
    def boom(_seq):
        raise RuntimeError("boom-record")

    mem.records_after = boom
    assert wait_until(lambda: not renderer.status()["healthy"], 3), renderer.status()
    bad = renderer.status()
    assert bad["alive"] is True, bad
    assert "boom-record" in bad["error"], bad
    print("render error reported ok")

    mem.records_after = original
    assert wait_until(lambda: renderer.status()["healthy"], 3), renderer.status()
    good = renderer.status()
    assert good["alive"] is True and good["error"] == "", good
    print("render recovered ok")
finally:
    mem.records_after = original
    renderer.shutdown()

assert renderer.status()["alive"] is False, renderer.status()
shutil.rmtree(home, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)

print("\nRENDER HEALTH TEST OK")
