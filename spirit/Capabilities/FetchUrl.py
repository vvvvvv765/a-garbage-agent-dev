"""
fetchUrl 能力：抓一个网页，转成文本，按 offset / max_chars 分段返回。

照 Claude Code 的 WebFetch 抄的部分：
  - HTTP 自动升级成 HTTPS（升级失败回退 HTTP）
  - localhost / 不带点的主机名直接拒绝（别拿它打内网）
  - 只收文本类响应（html / plain / json / xml）
  - 结果缓存 15 分钟
  - 长页面用 offset 续读
不抄的部分：它用一个小模型按 prompt 提纯；我们直接把文本交给主模型。
"""
import ipaddress
import re
import socket
import threading
import time
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .Executions import ExecutionCancelled, executions
from .Spec import CapabilitySpec

CACHE_TTL = 15 * 60
MAX_BYTES = 2 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 Spirit/1.0"
)

_cache = {}
_cache_lock = threading.Lock()


class _TextExtractor(HTMLParser):
    """HTML → 纯文本（标题留 #，列表留 -，其余按段落换行）。"""

    SKIP = {"script", "style", "noscript", "svg", "iframe", "template", "head"}
    BLOCK = {
        "p", "div", "section", "article", "header", "footer", "main",
        "tr", "table", "ul", "ol", "blockquote", "pre", "hr", "br",
        "h1", "h2", "h3", "h4", "h5", "h6", "li",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.title = ""
        self.__in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag == "title":
            self.__in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "title":
            self.__in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.__in_title:
            self.title += data
            return
        if not self.skip:
            self.parts.append(data)

    def text(self):
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw)
        return raw.strip()


def _literal_ip(host):
    """把 127.0.0.1 / 2130706433 / 0x7f000001 / 0177.0.0.1 都认出来。"""
    host = str(host or "").strip("[]").lower()
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if re.fullmatch(r"\d+", host):
        try:
            return ipaddress.ip_address(int(host))
        except (ValueError, OverflowError):
            return None
    if host.startswith("0x"):
        try:
            return ipaddress.ip_address(int(host, 16))
        except (ValueError, OverflowError):
            return None
    parts = host.split(".")
    if len(parts) == 4 and all(re.fullmatch(r"(?:0x[0-9a-f]+|\d+)", part) for part in parts):
        try:
            values = []
            for part in parts:
                if part.startswith("0x"):
                    values.append(int(part, 16))
                elif len(part) > 1 and part.startswith("0"):
                    values.append(int(part, 8))
                else:
                    values.append(int(part, 10))
            if all(0 <= value <= 255 for value in values):
                return ipaddress.ip_address(".".join(str(value) for value in values))
        except ValueError:
            return None
    return None


def _unsafe_ip(address):
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or getattr(address, "is_site_local", False)
    )


def _allowed(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "只支持 http / https"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "URL 里没有主机名"
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        return False, "不支持 localhost（本地服务请用 bash + curl）"
    if host.endswith(".local"):
        return False, "不支持 .local 内网域名"
    literal = _literal_ip(host)
    if literal is not None:
        if _unsafe_ip(literal):
            return False, f"不允许访问内网 / 保留地址（{literal}）"
        return True, None
    if "." not in host:
        return False, "不支持 localhost 或不带点的主机名（本地服务请用 bash + curl）"
    try:
        infos = socket.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as error:
        return False, f"域名解析失败：{error}"
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if _unsafe_ip(address):
            return False, f"域名解析到内网 / 保留地址（{address}）"
    return True, None


class _Fatal(Exception):
    """重试也没用的错（HTTP 4xx / 不是文本页）。"""


class _SafeRedirect(HTTPRedirectHandler):
    """每一跳都重新做 SSRF 校验，别让 302 跳进内网。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, reason = _allowed(newurl)
        if not ok:
            raise _Fatal(f"重定向被拒绝：{reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = build_opener(_SafeRedirect())


def _get(candidate, timeout):
    request = Request(candidate, headers={"User-Agent": USER_AGENT})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            final = response.geturl()
            ok, reason = _allowed(final)
            if not ok:
                raise _Fatal(f"跳转后的地址被拒绝：{reason}")
            content_type = response.headers.get_content_type()
            if not (
                content_type.startswith("text/")
                or content_type in ("application/json", "application/xml",
                                    "application/xhtml+xml")
            ):
                raise _Fatal(f"不是文本页面（Content-Type: {content_type}）")
            chunks = []
            total = 0
            while total <= MAX_BYTES:
                executions.check()   # 分段读，取消能尽快生效
                chunk = response.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            data = b"".join(chunks)
            charset = response.headers.get_content_charset() or "utf-8"
        if len(data) > MAX_BYTES:
            data = data[:MAX_BYTES]
        return candidate, final, content_type, data.decode(charset, errors="replace")
    except HTTPError as error:
        raise _Fatal(f"HTTP {error.code}：{error.reason}") from error


def _download(url, timeout):
    """抓取：HTTP 先升 HTTPS（失败回退）；网络类错误整体重试一次。"""
    candidates = [url]
    if url.startswith("http://"):
        candidates = ["https://" + url[len("http://"):], url]

    last_error = None
    for attempt in range(2):
        for candidate in candidates:
            try:
                return _get(candidate, timeout)
            except _Fatal:
                raise
            except Exception as error:      # SSL 抖动 / 连接被掐 / 超时
                last_error = error
        if attempt == 0:
            time.sleep(0.4)
    raise last_error


def _render(url, timeout):
    """返回 (请求地址, 最终地址, 标题, 正文, 是否命中缓存)。"""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1], hit[2], hit[3], hit[4], True

    requested, final, content_type, body = _download(url, timeout)
    if "html" in content_type or "xml" in content_type:
        extractor = _TextExtractor()
        extractor.feed(body)
        text = extractor.text()
        title = extractor.title.strip()
    else:
        text = body
        title = ""

    with _cache_lock:
        _cache[url] = (now, requested, final, title, text)
    return requested, final, title, text, False


class FetchUrlCapability:
    name = "fetchUrl"
    description = (
        "抓取一个网页（http/https），把 HTML 转成文本返回；自动 HTTPS、拒绝 localhost、"
        "结果缓存 15 分钟。页面很长时用 offset / max_chars 分段读。"
        "依赖 JS 渲染或需要登录的页面抓不到，那种请用 bash 或浏览器工具。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓的网页地址"},
            "offset": {"type": "integer", "description": "从第几个字符开始读，默认 0"},
            "max_chars": {"type": "integer", "description": "最多返回多少字符，默认 3000"},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, timeout=30,
            trust="untrusted", side_effect="external",
        )

    def run(self, arguments):
        executions.check()
        url = str(arguments["url"]).strip()
        ok, problem = _allowed(url)
        if not ok:
            return problem

        try:
            requested, final, title, text, cached = _render(url, timeout=20)
        except ExecutionCancelled:
            raise
        except Exception as error:
            return f"抓取失败：{error}"
        executions.check()

        offset = max(0, int(arguments.get("offset", 0)))
        max_chars = max(200, min(int(arguments.get("max_chars", 3000)), 20000))
        total = len(text)
        if offset >= total:
            return f"已到页面末尾（全文 {total} 字符）"

        chunk = text[offset:offset + max_chars]
        header = [f"# 来源：{requested}"]
        if final != requested:
            header.append(f"# 最终地址：{final}")
        if title:
            header.append(f"# 标题：{title}")
        header.append(f"# 共 {total} 字符，显示 {offset}–{min(total, offset + max_chars)}"
                      + ("（缓存）" if cached else ""))

        body = "\n".join(header) + "\n\n" + chunk
        if offset + max_chars < total:
            body += f"\n…（还有 {total - offset - max_chars} 字符；用 offset={offset + max_chars} 继续读）"
        return body
