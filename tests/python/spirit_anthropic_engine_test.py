"""Anthropic 全链路：本地假 Messages 服务 → BIOS → AnthropicAdapter → 数据表。"""
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


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        seen["path"] = self.path
        seen["body"] = json.loads(body or b"{}")
        payload = "".join([
            sse("message_start", {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 5,
                        "output_tokens": 1,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            }),
            sse("content_block_start", {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }),
            sse("content_block_delta", {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "你好"},
            }),
            sse("content_block_stop", {
                "type": "content_block_stop",
                "index": 0,
            }),
            sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 2},
            }),
            sse("message_stop", {"type": "message_stop"}),
        ]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

home = Path(tempfile.mkdtemp(prefix="spirit-anthropic-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-anthropic-work-"))
engine = Engine(home=home, workdir=work)
item = engine.save_provider({
    "name": "本地 Claude",
    "kind": "anthropic",
    "base_url": f"http://127.0.0.1:{port}",
    "api_key": "sk-ant-test",
    "models": ["claude-test"],
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

    assert seen.get("path") == "/v1/messages", seen
    body = seen.get("body") or {}
    assert body.get("model") == "claude-test", body
    assert body.get("stream") is True, body
    assert body.get("max_tokens"), body
    assert any(
        message.get("role") == "user"
        for message in body.get("messages", [])
    ), body.get("messages")

    texts = [record.payload for record in mem.view(ASSISTANT)]
    assert "你好" in texts, texts
    usage = mem.view(USAGE)
    assert usage, "没有 usage"
    last = usage[-1].payload
    assert last.get("input") == 5 and last.get("output") == 2, last
    print("anthropic engine round ok")
finally:
    engine.stop()
    server.shutdown()
    server.server_close()
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

print("\nANTHROPIC ENGINE TEST OK")
