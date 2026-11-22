"""K4b Web API：额外会话能单独发消息 / 取历史 / 取用量，不串主会话。"""
import json
import os
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
        chunks = [
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "收到"},
                          "finish_reason": None}]},
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
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

home = Path(tempfile.mkdtemp(prefix="spirit-mapi-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-mapi-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

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
try:
    sent = http.post("/api/send", json={"text": "只在额外会话", "session": runtime.id})
    assert sent.status_code == 200 and sent.get_json()["session"] == runtime.id, sent.get_json()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not runtime.memory.view(ASSISTANT):
        time.sleep(0.1)
    texts = [record.payload for record in runtime.memory.view(ASSISTANT)]
    assert texts == ["收到"], texts

    history = http.get(f"/api/history?session={runtime.id}").get_json()
    kinds = [ev.get("type") for ev in history.get("events", [])]
    assert "user_message" in kinds and "assistant_message" in kinds, kinds

    usage = http.get(f"/api/usage?session={runtime.id}").get_json()
    assert usage.get("session", {}).get("requests", 0) >= 1, usage

    sessions = http.get("/api/sessions").get_json()
    match = [item for item in sessions if item.get("session") == runtime.id]
    assert match and match[0]["running"] is False, sessions
    print("multi-session web api ok:", runtime.id)
finally:
    runtime.stop()
    engine.stop()
    server.shutdown()
    server.server_close()
    render.shutdown()
print("\nMULTISESSION API TEST OK")
