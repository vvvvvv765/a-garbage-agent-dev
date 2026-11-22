"""内核长跑：两个会话连续多轮（带工具），看线程 / 执行 / 内存 / 落盘是否收敛。"""
import json
import os
import queue
import sys
import tempfile
import threading
import time
import tracemalloc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

TURNS = 20


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        has_tool = any(
            isinstance(message, dict) and message.get("role") == "tool"
            for message in messages
        )
        if not has_tool:
            delta = {
                "role": "assistant",
                "tool_calls": [{
                    "index": 0,
                    "id": f"call_{time.monotonic_ns()}",
                    "type": "function",
                    "function": {"name": "bash", "arguments": json.dumps({"command": "echo soak"})},
                }],
            }
            finish = "tool_calls"
        else:
            delta = {"role": "assistant", "content": "ok"}
            finish = "stop"
        chunks = [
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"id": "x", "object": "chat.completion.chunk", "created": 1,
             "model": "demo-chat",
             "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
             "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}},
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

home = Path(tempfile.mkdtemp(prefix="spirit-soak2-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-soak2-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import capabilities  # noqa: E402
from Capabilities.Executions import executions  # noqa: E402
from DC import DC  # noqa: E402
from Engine import Engine  # noqa: E402
from Memory import ASSISTANT, TOOL_OUTPUT  # noqa: E402
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
inbox = queue.Queue()
engine.set_input_source(inbox.get)
assert engine.start()
threading.Thread(target=engine.run, name="spirit-primary-loop", daemon=True).start()
runtime = engine.open_runtime()


def idle(timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not DC.turn_active and not runtime.running and runtime.queue_size == 0:
            return True
        time.sleep(0.05)
    return False


def count(memory, address):
    return len(memory.view(address))


def wait_assistant(memory, target, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if count(memory, ASSISTANT) >= target:
            return True
        time.sleep(0.05)
    return False


from Memory import mem as primary_mem  # noqa: E402

# 预热：把线程池 / worker / 渲染都拉起来
inbox.put("预热")
runtime.send("预热")
deadline = time.monotonic() + 20
while time.monotonic() < deadline and (
    count(primary_mem, ASSISTANT) < 1 or count(runtime.memory, ASSISTANT) < 1
):
    time.sleep(0.1)
assert idle(20), "预热没有回到空闲"

tracemalloc.start()
baseline_mem = tracemalloc.get_traced_memory()[0]
baseline_threads = threading.active_count()
started = time.monotonic()
first_turn_ms = None
last_turn_ms = None

try:
    for index in range(TURNS):
        target_p = count(primary_mem, ASSISTANT) + 1
        target_r = count(runtime.memory, ASSISTANT) + 1
        turn_started = time.monotonic()
        inbox.put(f"主会话第 {index + 1} 轮")
        runtime.send(f"额外会话第 {index + 1} 轮")
        assert wait_assistant(primary_mem, target_p), f"主会话第 {index} 轮没完成"
        assert wait_assistant(runtime.memory, target_r), f"额外会话第 {index} 轮没完成"
        assert idle(20), f"第 {index} 轮没有回到空闲"
        elapsed = (time.monotonic() - turn_started) * 1000
        if index == 0:
            first_turn_ms = elapsed
        last_turn_ms = elapsed

    current_mem = tracemalloc.get_traced_memory()[0]
    growth_mb = (current_mem - baseline_mem) / 1024 / 1024
    threads = threading.active_count()
    print(
        f"1. {TURNS} 轮 × 2 会话 ok（首轮 {first_turn_ms:.0f}ms，末轮 {last_turn_ms:.0f}ms，"
        f"Python 堆 +{growth_mb:.1f}MB，线程 {baseline_threads}->{threads}）"
    )
    assert growth_mb < 30, f"Python 堆增长过多：{growth_mb:.1f}MB"
    assert threads <= baseline_threads + 4, f"线程增长过多：{baseline_threads}->{threads}"

    # ---------- 2. 执行 / 工具池收敛 ----------
    stats = capabilities.stats()
    assert stats["active"] == 0, stats
    assert stats["worker"]["busy"] == 0, stats
    assert not executions.snapshot(), executions.snapshot()
    assert not executions.snapshot(runtime.id), executions.snapshot(runtime.id)
    print("2. 执行与 worker 池收敛 ok")

    # ---------- 3. 落盘水位与内容 ----------
    from Memory.Persist import persist as primary_persist  # noqa: E402

    for name, memory, store, path in (
        ("primary", primary_mem, primary_persist, engine.current_session()),
        ("runtime", runtime.memory, runtime.persist, runtime.current_path),
    ):
        assert path, f"{name} 没落盘"
        memory.flush()
        assert store.saved_seq >= memory.last_seq(), name
        text = Path(path).read_text(encoding="utf-8")
        assert '"address": "tool_output"' in text, name
        assert '"address": "assistant"' in text, name
    print("3. 两会话落盘一致 ok")

    # ---------- 4. 跑完还能继续用 ----------
    target = count(primary_mem, ASSISTANT) + 1
    inbox.put("收尾")
    assert wait_assistant(primary_mem, target, 20), "收尾轮没完成"
    assert idle(20)
    print("4. 长跑后仍可继续 ok")
finally:
    runtime.stop()
    try:
        inbox.put_nowait(None)
    except Exception:
        pass
    engine.stop()
    server.shutdown()
    server.server_close()
    render.shutdown()
print("\nKERNEL SOAK TEST OK")
