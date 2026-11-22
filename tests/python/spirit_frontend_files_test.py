"""前端静态文件完整性：不许有裸 CR（会把 /\\r?\\n/ 这类正则拆成非法字面量）。"""
from pathlib import Path

static = Path(os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit") + "/WebUI/static")

for name in ("app.js", "index.html", "provider-presets.js"):
    path = static / name
    assert path.exists(), f"缺文件 {path}"
    data = path.read_bytes()
    for index, byte in enumerate(data):
        if byte == 0x0D and (index + 1 >= len(data) or data[index + 1] != 0x0A):
            line = data[:index].count(b"\n") + 1
            raise AssertionError(f"{name} 第 {line} 行附近有裸 CR，正则可能被拆行")
    print(f"ok {name} ({len(data)} bytes)")

app = (static / "app.js").read_bytes()
assert b"function appendToolDelta" in app, "工具实时输出函数不见了"
assert b"split(/\\r?\\n/)" in app, "工具实时输出取最后一行的正则不对"
print("\nFRONTEND FILES TEST OK")
