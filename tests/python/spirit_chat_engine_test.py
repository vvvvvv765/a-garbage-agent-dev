"""Chat 接口全链路：本地假 OpenAI Chat 服务 → BIOS 句柄 → ChatAdapter → 数据表。"""
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

from Engine import Engine  # noqa: E402
from Memory import ASSISTANT, USAGE, mem  # noqa: E402

seen = {}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        seen["path"] = self.path
        seen["body"] = json.loads(body or b"{}")
        chunks = [
            {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "demo-chat",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": "你好"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "demo-chat",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        ]
        payload = "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks
        ) + "data: [DONE]\n\n"
        data = payload.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

home = Path(tempfile.mkdtemp(prefix="spirit-chat-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-chat-work-"))
engine = Engine(home=home, workdir=work)
item = engine.save_provider({
    "name": "本地 Chat",
    "kind": "openai-chat",
    "base_url": f"http://127.0.0.1:{port}/v1",
    "api_key": "sk-local",
    "models": ["demo-chat"],
    "pricing": {"input": 0, "output": 0, "currency": "CNY"},
})
engine.activate_provider(item["id"])

inputs = ["你好"]


def source():
    if inputs:
        return inputs.pop(0)
    raise EOFError


try:
    engine.set_input_source(source)
    assert engine.start(), "引擎没有启动"
    runner = threading.Thread(target=engine.run)
    runner.start()
    runner.join(timeout=20)
    assert not runner.is_alive(), "引擎没有在 EOF 后停下"
    engine.stop()

    assert seen.get("path") == "/v1/chat/completions", seen
    body = seen.get("body") or {}
    assert body.get("model") == "demo-chat", body
    assert body.get("stream") is True, body
    assert body.get("messages"), body
    assert any(
        message.get("role") == "user" and message.get("content") == "你好"
        for message in body["messages"]
    ), body["messages"]
    assert "tools" in body and body["tools"], "工具 schema 没有转换"

    texts = [record.payload for record in mem.view(ASSISTANT)]
    assert "你好" in texts, texts
    usage = mem.view(USAGE)
    assert usage, "没有 usage"
    last = usage[-1].payload
    assert last.get("input") == 5 and last.get("output") == 2, last
    print("chat engine round ok")
finally:
    engine.stop()
    server.shutdown()
    server.server_close()
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

print("\nCHAT ENGINE TEST OK")
