"""批 C：配置损坏留档、会话逐行容错、legacy 对账、可中断退避。"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Cancel import token as cancel_token  # noqa: E402
from Config import Providers, config  # noqa: E402
from DC.Reconnect import Reconnect  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-rec-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-rec-work-"))
os.environ["SPIRIT_HOME"] = str(home)

# ---------- 1. 配置损坏：留档 + 降级，不被静默覆盖 ----------
cfg_path = home / "config.json"
cfg_path.write_text('{"llm": {"providers": [', encoding="utf-8")   # 半截 JSON
config.load()
assert config.degraded is True
assert "备份" in config.load_message, config.load_message
corrupt = list(home.glob("config.json.corrupt-*"))
assert corrupt, "坏配置应该改名留档"
assert corrupt[0].read_text(encoding="utf-8").startswith('{"llm"'), corrupt
config.set("engine.max_steps", 5)
config.save()
assert (home / "config.json").exists()
# 再存一次才产生 .bak（第一次目标不存在）
config.save()
assert (home / "config.json.bak").exists()
assert corrupt[0].exists(), "留档不能被后续保存删掉"
print("1. 配置损坏留档 ok")

# ---------- 2. 会话逐行容错 ----------
engine = Engine(home=home, workdir=work)
session_dir = Path(engine.session_dir)
session_dir.mkdir(parents=True, exist_ok=True)
bad = session_dir / "session-20260101-000000.jsonl"
bad.write_text(
    json.dumps({"seq": 1, "address": "user", "payload": "第一句"}, ensure_ascii=False) + "\n"
    + '{"seq": 2, "address": "assistant", "payload": "半截' + "\n"
    + json.dumps({"seq": 3, "address": "user", "payload": "第二句"}, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
events = engine.load_session(str(bad))
assert [e["type"] for e in events] == ["user_message", "user_message"], events
assert engine.session_warnings() and "1" in engine.session_warnings()[0], engine.session_warnings()
print("2. 会话逐行容错 ok")

# ---------- 3. legacy kind 不再写死 openai；顶层对账 ----------
legacy_home = Path(tempfile.mkdtemp(prefix="spirit-rec-legacy-"))
(legacy_home / "config.json").write_text(json.dumps({
    "llm": {
        "provider": "anthropic",
        "provider_id": "x",
        "base_url": "https://relay.test",
        "api_key": "sk-legacy",
        "model": "m",
    }
}, ensure_ascii=False), encoding="utf-8")
config.load(str(legacy_home / "config.json"))
assert Providers.current_kind(config) == "anthropic", Providers.current_kind(config)
legacy_items = Providers.providers_of(config)
assert legacy_items[0]["kind"] == "anthropic", legacy_items

# providers 列表存在但顶层 kind 是旧的 → sync_active 对齐
config.set("llm.providers", [{
    "id": "p1", "name": "P1", "kind": "anthropic", "base_url": "https://p1.test",
    "api_key": "sk", "models": ["m"],
}])
config.set("llm.provider_id", "p1")
config.set("llm.provider", "openai")   # 过期顶层
Providers.sync_active(config)
assert config.get("llm.provider") == "anthropic", config.get("llm.provider")
assert config.get("llm.base_url") == "https://p1.test"
print("3. legacy / 对账 ok")

# ---------- 4. 退避可中断 ----------
class Boom(Exception):
    pass


def fetch():
    raise Boom("网络错误")


r = Reconnect(max_attempts=5, base_delay=5, max_delay=5)
cancel_token.clear()
started = time.time()
cancel_token.set()
try:
    result = r.chat(fetch, lambda stream: [])
finally:
    cancel_token.clear()
assert result.ok is False and result.error == "已取消", result
assert time.time() - started < 1.0, "取消后不该再等退避"
print("4. 可中断退避 ok")

print("ALL RECOVERY TESTS PASSED")
