"""图片输入：上传 / 发送队列 / 三种方言转换 / 历史回放。"""
import base64
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-img-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Config import config  # noqa: E402
from Disk import disk  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.Bundle import ContextBundle  # noqa: E402
from Memory import USER, mem  # noqa: E402
from Provider.Adapter import (  # noqa: E402
    _to_anthropic_messages, _to_chat_messages, _to_responses_input,
)
from WebUI import server as web  # noqa: E402
from WebUI.Input import inputs  # noqa: E402

home = Path(tempfile.mkdtemp(prefix="spirit-img-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-img-work-"))
engine = Engine(home=home, workdir=work)
config.set("engine.capability_isolation", False)
web._engine = engine
client = web.test_client()

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAusB9Y9Z1ZkAAAAASUVORK5CYII="
)

# ---------- 1. 上传 / 读取 ----------
res = client.post("/api/upload", json={"data": f"data:image/png;base64,{PNG}"}).get_json()
assert res["ok"] and res["id"].endswith(".png"), res
name = res["id"]
saved = disk.area("uploads") / name
assert saved.exists() and saved.stat().st_size > 0
served = client.get(f"/api/upload/{name}")
assert served.status_code == 200 and served.data == saved.read_bytes()
print("1. 上传 / 读取 ok")

# ---------- 2. /api/send 带图片进队列 ----------
while not inputs.empty():
    inputs.get_nowait()
res = client.post("/api/send", json={"text": "看看这个", "images": [name]}).get_json()
assert res["ok"], res
payload = inputs.get_nowait()
assert isinstance(payload, dict) and payload["text"] == "看看这个", payload
assert payload["images"][0]["id"] == name, payload
print("2. 发送队列 ok")

# ---------- 2b. 边界：类型 / 数量 / 失效 id ----------
bad = client.post("/api/upload", json={"data": f"data:image/svg+xml;base64,{PNG}"})
assert bad.status_code == 400, bad.get_json()
many = client.post("/api/send", json={"text": "", "images": [name] * 5})
assert many.status_code == 400, many.get_json()
missing = client.post("/api/send", json={"text": "", "images": ["0" * 32 + ".png"]})
assert missing.status_code == 400, missing.get_json()
assert client.get("/api/upload/not-an-image.png").status_code == 404
print("2b. 图片边界 ok")

# ---------- 3. 三种方言 ----------
bundle = ContextBundle(
    instructions=None,
    messages=(
        {"role": "user", "content": "看看这个", "images": [{"id": name, "mime": "image/png"}]},
    ),
)
chat = _to_chat_messages(bundle)
assert chat[-1]["content"][0] == {"type": "text", "text": "看看这个"}
assert chat[-1]["content"][1]["type"] == "image_url"
assert chat[-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")

anthropic = _to_anthropic_messages(bundle)
blocks = anthropic[-1]["content"]
assert blocks[0] == {"type": "text", "text": "看看这个"}
assert blocks[1]["type"] == "image" and blocks[1]["source"]["type"] == "base64"
assert blocks[1]["source"]["media_type"] == "image/png"

responses = _to_responses_input(bundle)
parts = responses[-1]["content"]
assert parts[0] == {"type": "input_text", "text": "看看这个"}
assert parts[1]["type"] == "input_image"
assert parts[1]["image_url"].startswith("data:image/png;base64,")
print("3. 三种方言 ok")

# ---------- 4. 历史回放带图片 ----------
mem.clear()
mem.submit(USER, {"text": "看看这个", "images": [{"id": name, "mime": "image/png"}]})
mem.flush()
events = engine.history_events()
user_events = [item for item in events if item.get("type") == "user_message"]
assert user_events and user_events[-1]["images"][0]["url"].endswith(name), user_events
print("4. 历史回放 ok")

print("\nALL IMAGE TESTS PASSED")
