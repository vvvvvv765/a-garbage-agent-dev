"""per-provider 上下文窗口 / 最大输出：跟着当前提供商走，不影响全局设置。"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Config import Providers, config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Provider import Adapter as ad_mod  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-pp-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-pp-work-"))
engine = Engine(home=home, workdir=work)

# 全局默认保持不动
global_window = config.get("llm.context_window")
global_max = config.get("llm.max_tokens")
assert global_window == 128000 and global_max == 8192, (global_window, global_max)

a = engine.save_provider({
    "name": "A", "base_url": "https://a.test", "models": ["m"],
    "context_window": 64000, "max_tokens": 4096,
})
assert a["context_window"] == 64000 and a["max_tokens"] == 4096, a
engine.activate_provider(a["id"])
assert Providers.active_value(config, "context_window", 128000) == 64000
assert Providers.active_value(config, "max_tokens", 8192) == 4096
assert config.get("llm.context_window") == 128000, "全局设置不该被提供商覆盖"
assert gpu.context_stats()["window"] == 64000, gpu.context_stats()
print("1. A 的窗口 / 输出 ok")

# Adapter 发请求用这家自己的 max_tokens
class Handle:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        class Empty:
            def __iter__(self): return iter(())
            def close(self): pass
        return Empty()


h = Handle()
ad_mod._ANTHROPIC.create(h, ContextBundle("", ()), [], False)
assert h.kwargs["max_tokens"] == 4096, h.kwargs["max_tokens"]
print("2. 请求按 provider 的 max_tokens ok")

# 切到没写窗口的 B → 回落到全局
b = engine.save_provider({"name": "B", "base_url": "https://b.test", "models": ["m"]})
engine.activate_provider(b["id"])
assert Providers.active_value(config, "context_window", 128000) == 128000
assert Providers.active_value(config, "max_tokens", 8192) == 8192
assert gpu.context_stats()["window"] == 128000
print("3. 未配置回落到全局 ok")

# 全局设置仍可改（作为回退值）
config.set("llm.context_window", 32000)
config.save()
assert Providers.active_value(config, "context_window", 128000) == 32000
print("4. 全局回退 ok")

# 校验
for bad in ({"context_window": 500}, {"max_tokens": 10}, {"context_window": "x"}):
    try:
        engine.save_provider({"name": "bad", "base_url": "https://x.test",
                              "models": ["m"], **bad})
        raise AssertionError(f"坏值应报错：{bad}")
    except ValueError:
        pass
print("5. 校验 ok")

# 导入 / 复制保留字段
copy = engine.duplicate_provider(a["id"])
copied = next(p for p in copy["providers"] if p["id"].startswith(a["id"]))
assert copied["context_window"] == 64000 and copied["max_tokens"] == 4096, copied
res = engine.import_providers({"providers": [{
    "id": "imp", "name": "导入", "base_url": "https://imp.test", "models": ["m"],
    "context_window": 200000, "max_tokens": 16000,
}]})
imported = next(p for p in res["providers"] if p["id"] == "imp")
assert imported["context_window"] == 200000 and imported["max_tokens"] == 16000, imported
print("6. 复制 / 导入保留 ok")

print("ALL PER-PROVIDER TESTS PASSED")
