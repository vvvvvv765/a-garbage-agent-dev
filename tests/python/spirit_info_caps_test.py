"""四类能力第一批：httpRequest / httpProbe / portScan / dnsLookup。"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-info-sessions-")
for name in ("SPIRIT_HOME", "SPIRIT_WORKDIR", "SPIRIT_LOG_DIR"):
    os.environ.pop(name, None)

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Engine import Engine  # noqa: E402

work = Path(tempfile.mkdtemp(prefix="spirit-info-work-"))
home = Path(tempfile.mkdtemp(prefix="spirit-info-home-"))
engine = Engine(home=home, workdir=work)
engine.use_scenario("pentest")   # portScan 只在渗透场景
engine.set_approval("auto")
assert engine.start()
# 这些旧能力已从渗透场景清单移除；测试直接启用它们验证实现
for _name in ('portScan', 'httpProbe', 'dnsLookup'):
    capabilities.registry.enable(_name)

PNG = b"\x00\x01\x02binary\xff"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def _send(self, status, body, content_type="text/plain", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(
                200,
                b"<html><head><title>Spirit Probe Test</title></head>"
                b"<body>hello</body></html>",
                "text/html; charset=utf-8",
                {"Server": "SpiritTest/1.0"},
            )
        elif self.path == "/redirect":
            self._send(302, b"", headers={"Location": "/final"})
        elif self.path == "/final":
            self._send(200, b"final-body", "text/plain; charset=utf-8")
        elif self.path == "/binary":
            self._send(200, PNG, "application/octet-stream")
        elif self.path == "/headers":
            self._send(200, json.dumps(dict(self.headers)).encode(), "application/json")
        else:
            self._send(404, b"not-found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self._send(
            200,
            json.dumps({
                "method": self.command,
                "content_type": self.headers.get("Content-Type", ""),
                "body": body.decode("utf-8", errors="replace"),
                "x_test": self.headers.get("X-Test", ""),
            }, ensure_ascii=False).encode(),
            "application/json",
        )


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"


def call(name, **arguments):
    raw = json.dumps(arguments, ensure_ascii=False)
    return capabilities.run([CapabilityInput(f"c-{name}", name, raw, arguments)])[0]


# ---------- 1. httpRequest 基本 / 跳转 / POST ----------
out = call("httpRequest", url=base + "/headers", headers={"X-Test": "abc"})
assert out.ok and "200" in out.content and "SpiritTest" not in out.content, out.content
assert "x-test" in out.content.lower() or "X-Test" in out.content, out.content
print("1. httpRequest 基本 ok")

out = call("httpRequest", url=base + "/redirect")
assert out.ok and "最终地址" in out.content and "/final" in out.content, out.content
assert "302" in out.content and "200" in out.content, out.content
print("2. 跳转链 ok")

out = call("httpRequest", url=base + "/redirect", follow_redirects=False)
assert out.ok and "302" in out.content and "Location" in out.content, out.content
print("3. 不跟随跳转 ok")

out = call(
    "httpRequest", url=base + "/echo", method="POST", json={"a": 1, "b": "中文"},
    headers={"X-Test": "post-header"},
)
assert out.ok and "200" in out.content, out.content
assert '"method": "POST"' in out.content or '"method":"POST"' in out.content, out.content
assert "post-header" in out.content and "中文" in out.content, out.content
print("4. POST JSON ok")

# ---------- 2. 二进制落盘 ----------
out = call("httpRequest", url=base + "/binary", save_path="downloads/pixel.bin")
assert out.ok and "已保存" in out.content, out.content
saved = work / "downloads" / "pixel.bin"
assert saved.read_bytes() == PNG, saved
assert "sha256" in out.content
print("5. 二进制落盘 ok")

# ---------- 3. httpProbe ----------
out = call("httpProbe", urls=[base + "/", base + "/redirect", "http://127.0.0.1:1/"])
assert out.ok, out.content
assert "Spirit Probe Test" in out.content and "200" in out.content, out.content
assert "失败" in out.content, out.content
print("6. httpProbe ok")

# ---------- 4. portScan ----------
probe = __import__("socket")
holder = probe.socket()
holder.bind(("127.0.0.1", 0))
closed_port = holder.getsockname()[1]
holder.close()
out = call("portScan", host="127.0.0.1", ports=f"{port},{closed_port}", timeout=0.3)
assert out.ok, out.content
assert f"{port}/tcp" in out.content, out.content
assert f"{closed_port}/tcp" not in out.content, out.content
print("7. portScan ok")

out = call("portScan", host="127.0.0.1", ports="top", timeout=0.05, concurrency=64)
assert out.ok and "端口扫描" in out.content, out.content
print("8. portScan top ok")

# ---------- 5. dnsLookup 参数校验 ----------
out = call("dnsLookup", domain="", record="A")
assert not out.ok or "不能为空" in out.content, out.content
out = call("dnsLookup", domain="example.com", record="BOGUS")
assert "不支持" in out.content, out.content
out = call("dnsLookup", domain="example.com", record="A,AAAA", timeout=3)
assert out.ok and "DNS example.com" in out.content, out.content
print("9. dnsLookup 形状 ok")

# ---------- 6. 进程隔离下也能跑 ----------
from Config import config  # noqa: E402

config.set("engine.capability_isolation", True)
out = call("httpRequest", url=base + "/final")
assert out.ok and "final-body" in out.content, out.content
out = call("dnsLookup", domain="example.com", record="BOGUS")
assert "不支持" in out.content, out.content
assert capabilities.stats()["worker"]["enabled"] is True, capabilities.stats()
print("10. worker 隔离 ok:", capabilities.stats()["worker"]["pids"])
capabilities.shutdown()
config.set("engine.capability_isolation", False)

server.shutdown()
capabilities.apply_scenario("daily")
print("\nALL INFO CAPABILITIES TESTS PASSED")
