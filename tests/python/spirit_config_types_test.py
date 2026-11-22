"""配置字段类型写坏：引擎照常启动，Providers / 用量接口不再 int('big') 崩。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

home = Path(tempfile.mkdtemp(prefix="spirit-cfg-types-"))
work = Path(tempfile.mkdtemp(prefix="spirit-cfg-types-work-"))
(home / "config.json").write_text(json.dumps({
    "llm": {
        "context_window": "big",     # 坏数字
        "max_tokens": "nope",
        "providers": [
            {
                "id": "x", "name": "X", "kind": "openai",
                "base_url": "https://x.test", "models": ["m"],
                "context_window": "big",  # providers 列表里也不在归一范围
                "max_tokens": None,
            }
        ],
    },
    "engine": {
        "keep_recent_turns": "many",  # 坏数字
        "summarize": "false",         # 字符串布尔（以前 bool("false") = True）
    },
}, ensure_ascii=False), encoding="utf-8")

from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402

engine = Engine(home=home, workdir=work)
print("engine booted")

assert config.get("llm.context_window") == 128000, config.get("llm.context_window")
assert config.get("llm.max_tokens") == 8192, config.get("llm.max_tokens")
assert config.get("engine.keep_recent_turns") == 2, config.get("engine.keep_recent_turns")
assert config.get("engine.summarize") is False, config.get("engine.summarize")
assert config.repairs, config.repairs
print("normalized:", config.repairs)

payload = engine.providers()
assert payload["providers"][0]["context_window"] == 0, payload["providers"][0]
assert payload["providers"][0]["max_tokens"] == 0, payload["providers"][0]
print("providers payload ok")

usage = engine.usage()
assert isinstance(usage, dict) and "session" in usage, usage
print("usage ok")

print("\nCONFIG TYPES TEST OK")
