"""fetchUrl 测试：HTML 转换 / 拒绝规则 / 分段 / 缓存。"""
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-fetch-")

import Capabilities.FetchUrl as fetch  # noqa: E402
from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402

# 这个用例打桩了 _download，必须在进程内跑；worker 隔离下桩不会传过去
config.set("engine.capability_isolation", False)


def call(**arguments):
    output = capabilities.run([CapabilityInput(
        "c-fetch", "fetchUrl", "{}", arguments,
    )])[0]
    return output.content


# 1. HTML 转换
html = """<html><head><title>测试页</title><script>bad()</script></head>
<body><h1>标题</h1><p>第一段</p><ul><li>一</li><li>二</li></ul></body></html>"""
extractor = fetch._TextExtractor()
extractor.feed(html)
text = extractor.text()
print("converted:", text.replace("\n", " | "))
assert extractor.title.strip() == "测试页"
assert "# 标题" in text and "- 一" in text
assert "bad()" not in text

# 2. 拒绝规则
assert "只支持 http" in call(url="ftp://example.com/a")
assert "localhost" in call(url="http://localhost:5000/")
assert "localhost" in call(url="http://intranet/x")

# 3. 抓取 + 分段 + 缓存（打桩，不依赖网络）
calls = []


def fake_download(url, timeout):
    calls.append(url)
    return url, url, "text/html", "<h1>A</h1><p>" + ("x" * 5000) + "</p>"


real_download = fetch._download
fetch._download = fake_download
fetch._cache.clear()

out1 = call(url="https://example.com/a", max_chars=500)
print("fetch1:", out1.splitlines()[0], "|", out1.splitlines()[-1][:60])
assert "# 标题" in out1 or "# 来源" in out1
assert "还有" in out1

out2 = call(url="https://example.com/a", offset=500, max_chars=500)
assert "显示 500–1000" in out2, out2

out3 = call(url="https://example.com/a", max_chars=500)
assert "（缓存）" in out3 or "缓存" in out3
assert len(calls) == 1, calls   # 三次调用只抓一次

# 4. 空页面 / 越界
out = call(url="https://example.com/a", offset=999999)
assert "已到页面末尾" in out, out

# 5. 真网络（可选）：恢复真实抓取再试
try:
    fetch._download = real_download
    fetch._cache.clear()
    real = call(url="https://example.com", max_chars=300)
    print("live:", real.splitlines()[0])
except Exception as error:
    print("live skipped:", error)

print("FETCH TEST OK")
