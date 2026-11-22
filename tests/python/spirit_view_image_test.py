"""viewImage：图片进上传区 → GPU 带上 → 三种方言都转成图像内容。"""
import base64
import os
import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-view-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-view-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import gpu  # noqa: E402
from Memory import TOOL_CALL, TOOL_OUTPUT, mem  # noqa: E402
from Provider.Adapter import (  # noqa: E402
    _to_anthropic_messages,
    _to_chat_messages,
    _to_responses_input,
)
from Render import render  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z1ZkAAAAASUVORK5CYII="
)
image = work / "pelican.png"
image.write_bytes(PNG)
text = work / "notes.txt"
text.write_text("hello", encoding="utf-8")

render.set_console(False)
engine = Engine(home=home, workdir=work)
engine.start()

# 1. viewImage 返回图片附件，并复制到上传区
# 能力体系执行完会自己把 tool_output 写进内存，这里只补一条 tool_call
mem.submit(TOOL_CALL, {
    "call_id": "c-img", "name": "viewImage", "arguments": '{"path":"pelican.png"}',
})
output = capabilities.run([CapabilityInput(
    "c-img", "viewImage", '{"path":"pelican.png"}', {"path": "pelican.png"},
)])[0]
assert output.ok, output
images = output.meta.get("images") or []
assert len(images) == 1, output.meta
name = images[0]["id"]
assert re.match(r"^[0-9a-f]{32}\.png$", name), name
saved = home / "uploads" / name
assert saved.exists() and saved.read_bytes() == PNG, saved
print("1. viewImage ok:", name)

# 2. readFile 遇到图片会提示用 viewImage
hint = capabilities.run([CapabilityInput(
    "c-hint", "readFile", '{"path":"pelican.png"}', {"path": "pelican.png"},
)])[0]
assert "viewImage" in hint.content, hint.content
print("2. readFile hint ok")

# 3. GPU 组装：tool_output 带上 images
mem.flush()
bundle = gpu.build_context(compact=False)
item = next(m for m in bundle.messages
            if isinstance(m, dict) and m.get("type") == "function_call_output")
assert item.get("images") and item["images"][0]["id"] == name, item
print("3. gpu carries image ok")

# 4. 三种方言都能转成图像内容
bundle_like = SimpleNamespace(messages=bundle.messages, instructions="")
responses = _to_responses_input(bundle_like)
r_item = next(m for m in responses
              if isinstance(m, dict) and m.get("type") == "function_call_output")
assert isinstance(r_item["output"], list), r_item
assert any(part.get("type") == "input_image" for part in r_item["output"]), r_item
print("4. responses image ok")

chat = _to_chat_messages(bundle_like)
assert any(m.get("role") == "tool" for m in chat), chat
assert any(
    m.get("role") == "user" and isinstance(m.get("content"), list)
    and any(part.get("type") == "image_url" for part in m["content"])
    for m in chat
), chat
print("5. chat image ok")

anthropic = _to_anthropic_messages(bundle_like)
tool_result = next(
    block for message in anthropic for block in message["content"]
    if block.get("type") == "tool_result"
)
assert isinstance(tool_result["content"], list), tool_result
assert any(part.get("type") == "image" for part in tool_result["content"]), tool_result
print("6. anthropic image ok")

# 7. 图片预算：同 id 去重，最多保留最新的 N 张
from Config import config  # noqa: E402

config.set("engine.max_images_per_request", 2)
mem.clear()
for index in range(5):
    ident = f"{index + 100:032x}.png"
    mem.submit(TOOL_CALL, {
        "call_id": f"cap{index}", "name": "viewImage",
        "arguments": '{"path":"pelican.png"}',
    })
    mem.submit(TOOL_OUTPUT, {
        "call_id": f"cap{index}",
        "output": "图片已附上",
        "meta": {"images": [{"id": ident, "mime": "image/png"}]},
    })
mem.flush()
bundle2 = gpu.build_context(compact=False)
outputs = [m for m in bundle2.messages
           if isinstance(m, dict) and m.get("type") == "function_call_output"]
attached = [image["id"] for item in outputs for image in (item.get("images") or [])]
assert len(attached) == 2, attached
assert attached == [f"{103:032x}.png", f"{104:032x}.png"], attached
print("7. image cap keeps newest ok:", attached)

mem.clear()
for call in ("dup1", "dup2"):
    mem.submit(TOOL_CALL, {
        "call_id": call, "name": "viewImage", "arguments": '{"path":"pelican.png"}',
    })
    mem.submit(TOOL_OUTPUT, {
        "call_id": call,
        "output": "图片已附上",
        "meta": {"images": [{"id": f"{200:032x}.png", "mime": "image/png"}]},
    })
mem.flush()
bundle3 = gpu.build_context(compact=False)
outputs = [m for m in bundle3.messages
           if isinstance(m, dict) and m.get("type") == "function_call_output"]
with_image = [item["call_id"] for item in outputs if item.get("images")]
assert with_image == ["dup2"], with_image
print("8. duplicate image only attached once ok")

render.shutdown()
print("\nVIEW IMAGE TEST OK")
