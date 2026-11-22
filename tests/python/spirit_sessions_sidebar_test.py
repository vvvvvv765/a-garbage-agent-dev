"""侧栏会话列表：运行中 / 未落盘的会话也要出现，且能切回去。"""
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


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        time.sleep(1.2)   # 让主会话保持在“运行中”，好观察侧栏
        chunks = [
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "在"},
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

home = Path(tempfile.mkdtemp(prefix="spirit-sidebar-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-sidebar-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from DC import DC  # noqa: E402
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
inbox = queue.Queue()
engine.set_input_source(inbox.get)
assert engine.start()
threading.Thread(target=engine.run, name="spirit-primary-loop", daemon=True).start()
web._engine = engine
http = web.test_client()

runtime = None
try:
    # ---------- 1. 主会话还在跑：侧栏就要能看到它（哪怕没落盘） ----------
    inbox.put("测试侧栏会话")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not DC.turn_active:
        time.sleep(0.05)
    assert DC.turn_active, "主会话没有进入运行状态"

    sessions = http.get("/api/sessions").get_json()
    primary = [item for item in sessions if item.get("session") == "primary"]
    assert primary, f"运行中的主会话不在侧栏：{sessions}"
    primary = primary[0]
    assert primary["running"] is True, primary
    assert primary["live"] is True, primary
    assert primary["title"] == "测试侧栏会话", primary
    assert primary["records"] > 0, primary
    # 轮内检查点可能已经建了文件；有没有文件都必须能显示 / 切换
    print("1. 运行中的主会话可见 ok")

    # ---------- 2. 主会话跑着时新开对话：两条都在侧栏 ----------
    created = http.post(
        "/api/session", json={"new": True, "session": "primary"}
    ).get_json()
    assert created["ok"] and created["session"] != "primary", created
    runtime = engine.runtime(created["session"])
    assert runtime is not None, created

    sessions = http.get("/api/sessions").get_json()
    ids = {item.get("session") for item in sessions}
    assert {"primary", runtime.id} <= ids, sessions
    fresh = [item for item in sessions if item.get("session") == runtime.id][0]
    assert fresh["live"] is True and fresh["path"] is None, fresh
    assert fresh["running"] is False, fresh
    print("2. 新对话立刻出现在侧栏 ok")

    browser = http.get("/api/browser?session=primary").get_json()
    assert browser["ok"] and "installed" in browser, browser
    kernel = http.get("/api/kernel").get_json()
    assert kernel["ok"] and "browser" in kernel, kernel
    print("2b. 浏览器设备状态 API ok")

    # ---------- 3. 新会话没记录 → 场景不该显示锁定；主会话已锁定 ----------
    fresh_state = http.get(f"/api/scenarios?session={runtime.id}").get_json()
    assert fresh_state["ok"] and fresh_state["locked"] is False, fresh_state
    primary_state = http.get("/api/scenarios").get_json()
    assert primary_state["ok"] and primary_state["locked"] is True, primary_state
    print("3. 场景锁定按会话判断 ok")

    # ---------- 4. 切回刚开始的对话：历史还在 ----------
    back = http.post("/api/session", json={"session": "primary"}).get_json()
    assert back["ok"] and back["session"] == "primary", back
    kinds = [event.get("type") for event in back.get("events", [])]
    assert "user_message" in kinds, kinds
    assert any(
        event.get("type") == "user_message" and "测试侧栏会话" in str(event.get("text") or "")
        for event in back.get("events", [])
    ), back.get("events")
    print("4. 切回原对话历史还在 ok")

    # ---------- 5. 轮次结束落盘后，同一条会话不会在侧栏出现两次 ----------
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not engine.primary_path:
        time.sleep(0.1)
    assert engine.primary_path, "轮次结束没有落盘"
    sessions = http.get("/api/sessions").get_json()
    same_path = [
        item for item in sessions
        if str(item.get("path") or "") == str(engine.primary_path)
    ]
    assert len(same_path) == 1, sessions
    assert same_path[0]["session"] == "primary", same_path
    print("5. 落盘后侧栏不重复 ok")
finally:
    if runtime is not None:
        runtime.stop()
    try:
        inbox.put_nowait(None)
    except Exception:
        pass
    engine.stop()
    server.shutdown()
    server.server_close()
    render.shutdown()
print("\nALL SIDEBAR SESSION TESTS PASSED")
