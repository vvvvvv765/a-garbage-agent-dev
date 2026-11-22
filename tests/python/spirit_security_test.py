"""安全体系（审批 + 审计）测试：模式 / 只读放行 / 拒绝回给模型 / 审计落盘。"""
import json
import os
import sys
import tempfile
from types import SimpleNamespace as NS

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-security-")

from Config import config  # noqa: E402
from DC.Security import security  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import TOOL_OUTPUT, mem  # noqa: E402
from Paths import log_dir  # noqa: E402
from Provider import adapter  # noqa: E402

DATA = config._Config__data  # 测试里临时改模式
config.set("engine.approval", "ask")   # 默认已改为 auto；这个测试专门验证 ask 语义
AUDIT = log_dir() / "audit.jsonl"
audit_before = len(AUDIT.read_text(encoding="utf-8").splitlines()) if AUDIT.exists() else 0

# ---------- 1. rules：只读直接放行，不惊动审批 ----------
asked = []
security.set_approver(lambda request: asked.append(request) or True)
allowed, reason = security.check("readFile", '{"path":"x.txt"}')
assert allowed and reason == "readonly", (allowed, reason)
assert not asked, asked
print("rules readonly ok")

# ---------- 2. rules：执行类要问；拒绝说清楚 ----------
security.set_approver(lambda request: False)
allowed, reason = security.check("bash", '{"bashinput":"echo hi"}')
assert not allowed, (allowed, reason)
assert "用户拒绝" in reason, reason
print("rules deny ok:", reason)

# ---------- 3. 审批回调可以带理由 ----------
security.set_approver(lambda request: (True, "用户允许"))
allowed, reason = security.check("writeFile", "{}")
assert allowed and reason == "用户允许", (allowed, reason)
print("approve ok")

# ---------- 4. 没接审批：安全默认拒绝 ----------
security.set_approver(None)
allowed, reason = security.check("writeFile", "{}")
assert not allowed and "没有接入审批" in reason, (allowed, reason)
print("no approver -> deny ok")

# ---------- 5. 查看范围：写类直接拒绝（不问）；读取放行 ----------
original_mode = DATA["engine"].get("approval", "ask")
original_access = DATA["engine"].get("access", "workspace")
DATA["engine"]["approval"] = "ask"
DATA["engine"]["access"] = "readonly"
try:
    asked.clear()
    security.set_approver(lambda request: asked.append(request) or True)
    allowed, reason = security.check("bash", "{}")
    assert not allowed and "查看" in reason, (allowed, reason)
    assert not asked, "查看范围下不该弹审批"
    allowed, _ = security.check("readFile", "{}")
    assert allowed
finally:
    DATA["engine"]["access"] = original_access
    DATA["engine"]["approval"] = original_mode
print("readonly access ok")

# ---------- 5b. ask 模式：外部调用要问 ----------
asked.clear()
security.set_approver(lambda request: asked.append(request) or True)
allowed, _ = security.check("fetchUrl", "https://example.com")
assert allowed and asked and asked[-1]["name"] == "fetchUrl", asked
print("ask asks external ok")

# ---------- 6. auto：不问，直接放行 ----------
DATA["engine"]["approval"] = "auto"
security.set_approver(None)
try:
    allowed, reason = security.check("bash", "{}")
    assert allowed and reason == "auto", (allowed, reason)
finally:
    DATA["engine"]["approval"] = original_mode
print("auto ok")

# ---------- 7. 审计落盘 ----------
lines = [json.loads(line) for line in AUDIT.read_text(encoding="utf-8").splitlines()]
assert len(lines) >= audit_before + 6, (audit_before, len(lines))
last = lines[-1]
assert {"time", "capability", "call_id", "arguments", "allowed", "reason"} <= set(last), last
print("audit ok:", len(lines), "lines")

# ---------- 8. 拒绝真的回给模型（假模型全链路） ----------
config.set("engine.approval", "ask")   # 引擎可能已重新 load，按当前对象再设一次
DATA = config._Config__data
DATA["engine"]["restore"] = False


def fake_model(call_id, command):
    counter = {"n": 0}

    def create(handle, bundle, schemas, thinking_on, effort="medium"):
        counter["n"] += 1
        if counter["n"] == 1:
            item = NS(
                type="function_call", call_id=call_id, name="bash",
                arguments=json.dumps({"bashinput": command}),
            )
            return iter([NS(type="response.completed", response=NS(output=[item]))])
        return iter([
            NS(type="response.output_text.delta", delta="结束"),
            NS(type="response.completed", response=NS(output=[])),
        ])

    return create


def run_once(approver, call_id, command):
    original = adapter.create
    adapter.create = fake_model(call_id, command)
    security.set_approver(approver)
    try:
        mark = len(mem.records())
        seen = []

        def source():
            if seen:
                raise EOFError
            seen.append(1)
            return "跑个命令"

        engine = Engine()
        config.set("engine.approval", "ask")   # Engine() 会重新 load（默认已是 auto），这里强制 ask
        engine.set_input_source(source)
        assert engine.start()
        engine.run()
        mem.flush()
        return [r.payload for r in mem.records_after(mark) if r.address == TOOL_OUTPUT]
    finally:
        adapter.create = original


outputs = run_once(lambda request: False, "call_deny", "echo SHOULD_NOT_RUN")
assert outputs, "no tool output"
assert any("用户拒绝" in str(o.get("output")) for o in outputs), outputs
assert not any("SHOULD_NOT_RUN" in str(o.get("output")) for o in outputs), outputs
print("deny reaches model ok:", outputs[0].get("output"))

outputs = run_once(lambda request: True, "call_allow", "echo APPROVED_OK")
assert any("APPROVED_OK" in str(o.get("output")) for o in outputs), outputs
print("allow runs command ok:", outputs[0].get("output").strip())

print("\nSECURITY TEST OK")
