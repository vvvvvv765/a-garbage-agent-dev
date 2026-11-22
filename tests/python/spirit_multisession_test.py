"""K4b：两个额外会话真并行跑模型，各自内存 / 落盘互不串。"""
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

requests = []
arrivals = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        arrivals.append(time.monotonic())
        requests.append(body)
        # 让两个会话的流重叠，证明是真并发而不是排队
        time.sleep(0.3)
        chunks = [
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": "你好"},
                          "finish_reason": None}]},
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
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

home = Path(tempfile.mkdtemp(prefix="spirit-multi-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-multi-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import ASSISTANT, mem as primary_mem  # noqa: E402
from Render import render  # noqa: E402

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
assert engine.start(), "engine not started"

first = engine.open_runtime()
second = engine.open_runtime()
started = time.monotonic()
first.send("A")
second.send("B")


def wait_for(runtime, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runtime.memory.view(ASSISTANT):
            return True
        time.sleep(0.1)
    return False


try:
    assert wait_for(first), "first session no answer"
    assert wait_for(second), "second session no answer"
    elapsed = time.monotonic() - started
    assert len(requests) == 2, requests
    # 判并发看“两个请求到达 server 的时间差”：串行时第二个要等第一个跑完
    # （≥0.3s）才到；并行时几乎同时到。不看总耗时——线程启动/GC 会让它偏大。
    assert len(arrivals) == 2, arrivals
    gap = abs(arrivals[1] - arrivals[0])
    assert gap < 0.25, f"sessions look serialized: gap={gap:.2f}s total={elapsed:.2f}s"
    assert [r.payload for r in first.memory.view(ASSISTANT)] == ["你好"]
    assert [r.payload for r in second.memory.view(ASSISTANT)] == ["你好"]
    assert not primary_mem.view(ASSISTANT), "额外会话污染了主会话内存"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not (
        first.persist.current_path and second.persist.current_path
    ):
        time.sleep(0.1)
    paths = {first.persist.current_path, second.persist.current_path}
    assert all(paths), paths
    assert len(paths) == 2, f"会话文件撞名：{paths}"
    print("multi-session parallel ok:", round(elapsed, 2), "s", paths)

    # 停掉一个额外会话，不能把共享能力体系收掉（另一个会话/主线程还能用工具）
    first.stop()
    time.sleep(0.4)
    second.send("第二次")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and len(second.memory.view(ASSISTANT)) < 2:
        time.sleep(0.1)
    assert len(second.memory.view(ASSISTANT)) >= 2, "停掉一个会话后另一个不再工作"
    out = capabilities.run([CapabilityInput(
        "after-stop", "listDir", '{"path":"."}', {"path": "."}
    )])[0]
    assert out.ok, out.content
    print("stop one runtime keeps shared capabilities ok")
finally:
    first.stop()
    second.stop()
    engine.stop()
    server.shutdown()
    server.server_close()
    render.shutdown()
print("\nMULTISESSION TEST OK")
