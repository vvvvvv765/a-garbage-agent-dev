"""故障转移（照抄 cc-switch 的队列 + 熔断）：队列顺序、熔断、CPU 里真的换一家重试。"""
import os
import sys
import tempfile
import time
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

from Bus import NT, keys  # noqa: E402
from Config import config  # noqa: E402
from Contract import Contract  # noqa: E402
from DC.CPU import CPU  # noqa: E402
from DC.Failover import failover  # noqa: E402
from DC.Reconnect import AttemptResult, reconnect  # noqa: E402
from Engine import Engine  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-fo-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-fo-work-"))
engine = Engine(home=home, workdir=work)

# ---------- 1. 数据模型 + 队列顺序 ----------
a = engine.save_provider({
    "name": "主家", "base_url": "https://a.test", "models": ["m"],
    "api_key": "sk-a", "in_failover_queue": True,
})
b = engine.save_provider({
    "name": "备家", "base_url": "https://b.test", "models": ["m"],
    "api_key": "sk-b", "in_failover_queue": True,
})
c = engine.save_provider({
    "name": "不排队", "base_url": "https://c.test", "models": ["m"],
    "api_key": "sk-c",
})
assert engine.providers()["providers"][-1]["in_failover_queue"] is False
assert failover.queue() == [a["id"], b["id"]], failover.queue()

engine.activate_provider(a["id"])
assert failover.current() == a["id"]
assert failover.next_after(a["id"]) == b["id"]
assert failover.next_after(b["id"]) == a["id"]
assert failover.next_after(c["id"]) is None, "不在队列里的不转移"
print("1. 队列顺序 ok")

# ---------- 2. 熔断：连续失败到阈值 → 冷却期跳过 → 到点恢复 ----------
config.set("engine.failover.enabled", True)
config.set("engine.failover.threshold", 4)
config.set("engine.failover.cooldown", 2)
failover.reset()
for _ in range(3):
    failover.record(a["id"], False)
assert failover.available(a["id"]), "没到阈值不该熔断"
failover.record(a["id"], False)
assert not failover.available(a["id"]), "到阈值应熔断"
assert failover.next_after(a["id"]) == b["id"], "熔断后应换下一家"
assert failover.next_after(b["id"]) is None, "只剩自己可用时没有下一家"
failover.record(a["id"], True)
assert failover.available(a["id"]), "成功一次应复位熔断"

failover.record(a["id"], False)
failover.record(a["id"], False)
failover.record(a["id"], False)
failover.record(a["id"], False)
assert not failover.available(a["id"])
snapshot = failover.snapshot()
assert snapshot[a["id"]]["open"] is True and snapshot[a["id"]]["open_in"] >= 0
time.sleep(2.2)   # 冷却期过去 → 半开
assert failover.available(a["id"]), "冷却期过后应允许再试"
failover.reset()
print("2. 熔断 ok")

# ---------- 3. CPU：请求失败后真的换一家重试 ----------
class FakeGPU:
    def __init__(self):
        self.calls = 0

    def request(self):
        self.calls += 1
        return object()


class FakeMemory:
    def last_seq(self, address=None):
        return 0

    def consume(self, stream, should_stop=None, epoch=0):
        return []

    def flush(self):
        pass

    def records_after(self, mark):
        return []


NT.register(keys.AGENT_START, Contract(SI=True))

switched = []


def fake_switch(provider_id):
    switched.append(provider_id)
    engine.activate_provider(provider_id)
    return True


cpu = CPU()
cpu.attach(gpu=FakeGPU(), memory=FakeMemory(), input_source=object(),
           switch_provider=fake_switch)

real_chat = reconnect.chat
calls = []


def fake_chat(fetch, consume):
    calls.append(1)
    if len(calls) == 1:
        return AttemptResult(False, [], "重连 5 次仍失败：模拟故障")
    return AttemptResult(True, [])


reconnect.chat = fake_chat
try:
    config.set("engine.failover.enabled", False)
    engine.activate_provider(a["id"])
    calls.clear()
    switched.clear()
    cpu._CPU__ask_model()
    assert len(calls) == 1 and not switched, (len(calls), switched)

    config.set("engine.failover.enabled", True)
    engine.activate_provider(a["id"])
    failover.reset()
    calls.clear()
    switched.clear()
    cpu._CPU__ask_model()
    assert switched == [b["id"]], switched
    assert len(calls) == 2, len(calls)
    assert failover.current() == b["id"], "切过去后当前提供商应变成备家"
    assert failover.snapshot().get(b["id"], {}).get("errors", 0) == 0

    # 备家也失败：不来回打转，试完就放弃
    calls.clear()
    switched.clear()

    def always_fail(fetch, consume):
        calls.append(1)
        return AttemptResult(False, [], "都挂了")

    reconnect.chat = always_fail
    engine.activate_provider(a["id"])
    failover.reset()
    result = cpu._CPU__ask_model()
    assert result == []
    assert len(switched) <= 2, switched
    assert len(calls) <= 3, calls

    # 当前这家已熔断 → 请求前就该换，而不是先白打一轮
    def ok_chat(fetch, consume):
        calls.append(1)
        return AttemptResult(True, [])

    reconnect.chat = ok_chat
    engine.activate_provider(a["id"])
    failover.reset()
    for _ in range(4):
        failover.record(a["id"], False)   # 连续失败到阈值，a 熔断
    calls.clear()
    switched.clear()
    cpu._CPU__ask_model()
    assert switched == [b["id"]], switched
    assert len(calls) == 1, calls
    assert failover.current() == b["id"]
finally:
    reconnect.chat = real_chat
print("3. CPU 换家重试 ok")

# ---------- 4. 设置接口 ----------
from WebUI import server as web  # noqa: E402
web._engine = engine
http = web.test_client()

state = http.get("/api/settings").get_json()
assert state["failover"] is True
res = http.post("/api/settings", json={"failover": False}).get_json()
assert res["ok"] and res["failover"] is False
assert config.get("engine.failover.enabled") is False
print("4. 设置接口 ok")

print("ALL FAILOVER TESTS PASSED")
