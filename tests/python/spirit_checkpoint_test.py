"""轮内检查点：模型回复 / 工具调用在工具还没跑完时就已落盘。"""
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

release = threading.Event()
calls = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        calls.append(body)
        first = len(calls) == 1
        if first:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": "call_slow",
                    "type": "function",
                    "function": {"name": "slow_wait", "arguments": "{}"},
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "全部完成"}
            finish = "stop"
        chunks = [
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}},
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

home = Path(tempfile.mkdtemp(prefix="spirit-ckpt-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-ckpt-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilitySpec  # noqa: E402
from DC import DC  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory.Addresses import ASSISTANT, TOOL_CALL, TOOL_OUTPUT, USER  # noqa: E402
from Render import render  # noqa: E402


class SlowCap:
    name = "slow_wait"
    description = "测试：卡住直到测试放行"
    parameters = {"type": "object", "properties": {}}

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters, side_effect="read")

    def run(self, arguments):
        release.wait(10)
        return "工具完成"


def addresses(path):
    found = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            found.append(json.loads(line).get("address"))
        except Exception:
            pass
    return found


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
engine.register_capability(SlowCap())
inbox = queue.Queue()
engine.set_input_source(inbox.get)
assert engine.start()
threading.Thread(target=engine.run, name="spirit-primary-loop", daemon=True).start()

try:
    inbox.put("跑一个慢工具")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not DC.turn_active:
        time.sleep(0.05)
    assert DC.turn_active, "本轮没有跑起来"

    # 工具还卡着（release 未放行），文件应该已经有本轮前半段
    path = None
    while time.monotonic() < deadline and not path:
        path = engine.primary_path
        if not path:
            time.sleep(0.05)
    assert path, "工具还没结束，会话文件没建出来"
    seen = addresses(path)
    assert USER in seen, seen
    assert TOOL_CALL in seen, seen   # 只有工具调用的回复没有 assistant 文本记录
    assert not DC.turn_active or not release.is_set()
    print("1. 工具执行前已落盘 ok:", seen)

    # 放行工具，等本轮结束
    release.set()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and DC.turn_active:
        time.sleep(0.05)
    assert not DC.turn_active, "本轮没有结束"
    seen = addresses(path)
    assert TOOL_OUTPUT in seen, seen
    assert seen.count(ASSISTANT) >= 1, seen
    print("2. 轮末补齐结果 ok:", seen)
finally:
    release.set()
    try:
        inbox.put_nowait(None)
    except Exception:
        pass
    engine.stop()
    server.shutdown()
    server.server_close()
    render.shutdown()
print("\nALL CHECKPOINT TESTS PASSED")
