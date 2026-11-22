"""nuclei 扫描 / gau 历史 URL：解析、写资产、超时保留部分结果。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-nuclei-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-nuclei-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import Assets  # noqa: E402
from Capabilities import Nuclei  # noqa: E402
from Render import render  # noqa: E402

render.set_console(False)

# ---------- 1. nuclei 结果解析 ----------
NUCLEI_OUT = "\n".join([
    json.dumps({"template-id": "CVE-2023-0001", "matched-at": "https://a.example.com/x",
                "host": "a.example.com",
                "info": {"name": "示例漏洞", "severity": "high"}}),
    json.dumps({"template-id": "tech-detect", "matched-at": "https://a.example.com/",
                "host": "a.example.com",
                "info": {"name": "技术指纹", "severity": "info"}}),
    "not-json-line",
])

calls = []


def fake_tool_run(name, args, timeout=300, cancel=None):
    calls.append((name, list(args)))
    return NUCLEI_OUT, "", 0, ""


Nuclei.tool_run = fake_tool_run
result = Nuclei.NucleiScanCapability().run({"target": "https://a.example.com", "severity": "high"})
assert result.ok and "命中 2 个" in result.content, result.content
assert "[high] 示例漏洞" in result.content, result.content
assets = Assets.list_assets("primary", limit=100)
urls = {item.get("url") for item in assets}
assert "https://a.example.com/x" in urls, urls
args = calls[0][1]
assert "-jsonl" in args and "-t" in args and "-severity" in args, args
print("1. nuclei 解析 + 写资产 ok")

# ---------- 2. nuclei 超时保留部分结果 ----------
def fake_timeout(name, args, timeout=300, cancel=None):
    return NUCLEI_OUT.splitlines()[0], "", None, "timeout"


Nuclei.tool_run = fake_timeout
result = Nuclei.NucleiScanCapability().run({"target": "https://b.example.com"})
assert result.ok and "超时截断" in result.content, result.content
print("2. nuclei 超时保留部分结果 ok")

# ---------- 3. gau 去重 + 写资产 ----------
GAU_OUT = "\n".join([
    "https://a.example.com/api?id=1",
    "https://a.example.com/api?id=1",
    "https://a.example.com/static/app.js",
    "not-a-url",
    "https://b.example.com/x?y=2#frag",
])

Nuclei.tool_run = lambda name, args, timeout=300, cancel=None: (GAU_OUT, "", 0, "")
result = Nuclei.GauUrlsCapability().run({"domain": "example.com"})
assert result.ok and "历史 URL 3 条" in result.content, result.content
assert "https://a.example.com/api?id=1" in result.content, result.content
rows = Assets.list_assets("primary", limit=500)
gauUrls = {item.get("url") for item in rows if "gau" in (item.get("sources") or [])}
assert "https://a.example.com/api?id=1" in gauUrls, gauUrls
assert "https://b.example.com/x?y=2" in gauUrls, gauUrls
assert not any("#frag" in url for url in gauUrls), gauUrls
print("3. gau 去重 + 写资产 ok")

# ---------- 4. 可用性 ----------
assert Nuclei.NucleiScanCapability().available() == (
    Nuclei.tool_path("nuclei") is not None and Path(Nuclei.DEFAULT_TEMPLATES).exists())
assert Nuclei.GauUrlsCapability().available() == (Nuclei.tool_path("gau") is not None)
print("4. 可用性判断 ok")

render.shutdown()
print("\nALL NUCLEI TESTS PASSED")
