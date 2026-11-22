"""会话级场景：额外会话用自己的场景（提示词 / 能力白名单），不改全局。"""
import json
import os
import queue
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

bodies = []
lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        with lock:
            bodies.append(body)
        chunks = [
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "好"},
                          "finish_reason": None}]},
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}},
        ]
        data = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
        data = (data + "data: [DONE]\n\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()

home = Path(tempfile.mkdtemp(prefix="spirit-scn-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-scn-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities.System import CapabilityScope, unuse_scope, use_scope  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import ASSISTANT  # noqa: E402
from Render import render  # noqa: E402
from WebUI import server as web  # noqa: E402

render.set_console(False)
engine = Engine(home=home, workdir=work)
provider = engine.save_provider({
    "name": "本地 Chat",
    "kind": "openai-chat",
    "base_url": f"http://127.0.0.1:{server.server_port}/v1",
    "api_key": "sk-local",
    "models": ["demo-chat"],
})
engine.activate_provider(provider["id"])
assert engine.start()
web._engine = engine
http = web.test_client()

runtime = engine.open_runtime()
primary_inbox = queue.Queue()
engine.set_input_source(primary_inbox.get)
threading.Thread(target=engine.run, name="spirit-primary-loop", daemon=True).start()


def wait_answer(session_memory, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if session_memory.view(ASSISTANT):
            return True
        time.sleep(0.05)
    return False


def request_text(index):
    with lock:
        return json.dumps(bodies[index], ensure_ascii=False)


try:
    # ---------- 1. 额外会话默认跟着创建时的场景 ----------
    state = http.get(f"/api/scenarios?session={runtime.id}").get_json()
    assert state["ok"] and state["current"] == "daily", state

    # ---------- 2. 切额外会话的场景：不动全局 ----------
    changed = http.post(
        "/api/scenario", json={"id": "pentest", "session": runtime.id}
    ).get_json()
    assert changed["ok"] and changed["current"] == "pentest", changed
    assert config.get("engine.scenario") == "daily", config.get("engine.scenario")
    global_state = http.get("/api/scenarios").get_json()
    assert global_state["current"] == "daily", global_state
    print("1. 额外会话切场景不改全局 ok")

    # ---------- 3. 额外会话的提示词是渗透，主会话还是日常 ----------
    runtime.send("会话场景测试")
    assert wait_answer(runtime.memory), "额外会话没有回答"
    text = request_text(0)
    assert "渗透测试场景" in text, text[:500]
    assert "日常场景" not in text, text[:500]

    primary_inbox.put("主会话场景测试")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and len(bodies) < 2:
        time.sleep(0.05)
    text = request_text(1)
    assert "日常场景" in text, text[:500]
    assert "渗透测试场景" not in text, text[:500]
    print("2. 两个会话的提示词互不串 ok")

    # ---------- 4. 本会话开过口之后，场景锁定 ----------
    again = http.post(
        "/api/scenario", json={"id": "daily", "session": runtime.id}
    )
    assert again.status_code == 409, again.get_json()
    print("3. 额外会话轮次后锁定 ok")

    # ---------- 5. 能力白名单按 scope 过滤 + 执行拒绝 ----------
    token = use_scope(CapabilityScope(["readFile"]))
    try:
        names = {schema["name"] for schema in capabilities.schemas()}
        assert names == {"readFile"}, names
        out = capabilities.run([CapabilityInput(
            "c-write", "writeFile", json.dumps({"path": "x.txt", "content": "x"}),
            {"path": "x.txt", "content": "x"},
        )])[0]
        assert not out.ok and "场景里没有" in out.content, out.content
    finally:
        unuse_scope(token)
    print("4. 会话能力白名单 ok")

    # ---------- 6. 删除额外会话：关运行时、删文件、死会话不再落到主会话 ----------
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not runtime.current_path:
        time.sleep(0.05)
    runtime_path = runtime.current_path
    assert runtime_path and Path(runtime_path).exists(), runtime_path
    removed = http.post("/api/session/delete", json={"path": runtime_path}).get_json()
    assert removed["ok"] and removed["deleted"], removed
    assert engine.runtime(runtime.id) is None
    assert not Path(runtime_path).exists()
    dead = http.post("/api/send", json={"text": "还在吗", "session": runtime.id})
    assert dead.status_code == 404, dead.get_json()
    print("5. 删除额外会话干净 ok")
finally:
    runtime.stop()
    try:
        primary_inbox.put_nowait(None)
    except Exception:
        pass
    engine.stop()
    server.shutdown()
    server.server_close()
    render.shutdown()
print("\nALL SESSION SCENARIO TESTS PASSED")
