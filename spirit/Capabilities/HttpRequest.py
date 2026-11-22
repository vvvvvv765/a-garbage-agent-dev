"""
httpRequest 能力：底层 HTTP 请求（侦察 / 验证 / 下载用）。

和 fetchUrl 的分工：
  - fetchUrl：面向阅读，SSRF 防护、只收文本、自动转正文
  - httpRequest：面向测试，保留原始状态 / 响应头 / 跳转链，可打 localhost / 内网，
    可自定义方法 / 头 / 请求体，可把二进制落到工作区

安全边界：命令灾难闸和路径沙箱仍由内核兜底；本能力不额外封目标
（授权渗透场景需要打内网 / 本机服务）。
"""
import base64
import hashlib
import json
import os
import re
import ssl
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

from .Executions import executions
from .Files import human_size, resolve
from .Sandbox import SandboxDenied
from .Spec import CapabilitySpec

METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
MAX_INLINE = 1024 * 1024
MAX_SAVE = 64 * 1024 * 1024
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 Spirit/1.0"
)
TEXT_TYPES = (
    "text/", "application/json", "application/javascript", "application/xml",
    "application/x-www-form-urlencoded", "application/xhtml+xml",
    "application/graphql", "application/problem+json",
)


class _NoRedirect(HTTPRedirectHandler):
    """不自动跟随：跳转链由能力自己记录和控制。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _normalize_headers(raw):
    headers = {}
    if not isinstance(raw, dict):
        return headers
    for key, value in raw.items():
        key = str(key or "").strip()
        if not key:
            continue
        headers[key] = str(value if value is not None else "")
        if len(headers) >= 100:
            break
    return headers


def _ssl_context(verify):
    if verify:
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def _opener(verify_tls=True, proxy=""):
    handlers = [_NoRedirect()]
    handlers.append(HTTPSHandler(context=_ssl_context(verify_tls)))
    if proxy:
        handlers.append(ProxyHandler({"http": proxy, "https": proxy}))
    return build_opener(*handlers)


def _read_stream(stream, limit):
    chunks = []
    total = 0
    truncated = False
    while True:
        executions.check()
        chunk = stream.read(min(65536, limit - total + 1))
        if not chunk:
            break
        if total + len(chunk) > limit:
            chunks.append(chunk[: limit - total])
            total = limit
            truncated = True
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks), truncated


def request_once(url, method="GET", headers=None, body=None, timeout=15.0,
                 verify_tls=True, proxy="", limit=MAX_INLINE):
    """发一次请求（不跟随跳转）；3xx / 4xx / 5xx 都当正常响应返回。"""
    request = Request(
        url,
        data=body,
        headers=headers or {},
        method=method.upper(),
    )
    opener = _opener(verify_tls, proxy)
    started = time.monotonic()
    try:
        response = opener.open(request, timeout=max(0.1, float(timeout)))
        try:
            status = int(getattr(response, "status", 0) or 0)
            reason = str(getattr(response, "reason", "") or "")
            response_headers = response.headers
            data, truncated = _read_stream(response, limit)
        finally:
            try:
                response.close()
            except Exception:
                pass
    except HTTPError as error:
        status = int(error.code)
        reason = str(error.reason or "")
        response_headers = error.headers
        data, truncated = _read_stream(error, limit)
        try:
            error.close()
        except Exception:
            pass
    except URLError as error:
        raise RuntimeError(f"连接失败：{error.reason}") from error
    return {
        "status": status,
        "reason": reason,
        "headers": response_headers,
        "body": data,
        "truncated": truncated,
        "seconds": round(time.monotonic() - started, 3),
    }


def perform(url, method="GET", headers=None, body=None, timeout=15.0,
            follow=True, max_redirects=5, verify_tls=True, proxy="",
            limit=MAX_INLINE):
    """按跳转链发请求；返回最后一跳 + 每一跳摘要。"""
    chain = []
    current = url
    current_method = method.upper()
    current_body = body
    final = None
    for hop in range(max(0, int(max_redirects)) + 1):
        result = request_once(
            current, current_method, headers, current_body,
            timeout=timeout, verify_tls=verify_tls, proxy=proxy, limit=limit,
        )
        location = ""
        try:
            location = result["headers"].get("Location") or ""
        except Exception:
            location = ""
        chain.append({
            "url": current,
            "status": result["status"],
            "reason": result["reason"],
            "location": location,
        })
        final = result
        final["url"] = current
        if not (
            follow
            and 300 <= result["status"] < 400
            and location
            and hop < max_redirects
        ):
            break
        current = urljoin(current, location)
        if result["status"] in (301, 302, 303) and current_method not in ("GET", "HEAD"):
            current_method = "GET"
            current_body = None
    final["chain"] = chain
    return final


def _header_lines(headers, limit=80):
    lines = []
    try:
        items = list(headers.items())
    except Exception:
        return lines
    for key, value in items[:limit]:
        text = str(value or "").replace("\r", " ").replace("\n", " ")[:500]
        lines.append(f"{key}: {text}")
    if len(items) > limit:
        lines.append(f"…（还有 {len(items) - limit} 个响应头）")
    return lines


def _is_text(headers):
    try:
        content_type = (headers.get("Content-Type") or "").lower()
    except Exception:
        content_type = ""
    return any(content_type.startswith(item) for item in TEXT_TYPES)


def _charset(headers):
    try:
        content_type = headers.get("Content-Type") or ""
    except Exception:
        content_type = ""
    match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    return match.group(1) if match else "utf-8"


class HttpRequestCapability:
    name = "httpRequest"
    description = (
        "发一次底层 HTTP 请求，返回状态码、响应头、跳转链、耗时和正文。"
        "可打 localhost / 内网、改方法 / 请求头 / 请求体；二进制响应用 save_path 落盘。"
        "与 fetchUrl 不同：这里不做 SSRF 过滤，也不把网页转成文章。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "完整 URL（http / https）"},
            "method": {
                "type": "string",
                "enum": list(METHODS),
                "description": "HTTP 方法，默认 GET",
            },
            "headers": {
                "type": "object",
                "description": "请求头键值对，例如 {\"Cookie\":\"a=1\"}",
                "additionalProperties": {"type": "string"},
            },
            "body": {"type": "string", "description": "字符串请求体"},
            "body_base64": {"type": "string", "description": "二进制请求体（base64）"},
            "json": {"description": "JSON 请求体；会自动序列化并设 Content-Type"},
            "follow_redirects": {"type": "boolean", "description": "是否跟随跳转，默认 true"},
            "max_redirects": {"type": "integer", "description": "最多跟几跳，默认 5，上限 10"},
            "timeout": {"type": "number", "description": "单次请求超时秒数，默认 15"},
            "verify_tls": {"type": "boolean", "description": "是否校验证书，默认 true"},
            "proxy": {"type": "string", "description": "可选代理，如 http://127.0.0.1:7890"},
            "max_bytes": {
                "type": "integer",
                "description": "正文最多读多少字节，默认 1MB，上限 10MB（save_path 时忽略）",
            },
            "save_path": {
                "type": "string",
                "description": "把完整响应体写到这个工作区路径（适合下载二进制）",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self):
        self.__workdir = None

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters, deps=("workdir",),
            trust="untrusted", side_effect="external", timeout=90, max_inline=6000,
        )

    def setup(self, deps):
        self.__workdir = deps.get("workdir")

    def run(self, arguments):
        url = str(arguments.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return "请求失败：url 必须是完整的 http / https 地址"
        method = str(arguments.get("method") or "GET").upper()
        if method not in METHODS:
            return f"请求失败：不支持的方法 {method}"
        headers = _normalize_headers(arguments.get("headers"))
        headers.setdefault("User-Agent", DEFAULT_UA)
        headers.setdefault("Accept", "*/*")

        body = None
        raw_body = arguments.get("body")
        raw_b64 = arguments.get("body_base64")
        if raw_b64:
            try:
                body = base64.b64decode(str(raw_b64), validate=True)
            except Exception:
                return "请求失败：body_base64 不是合法 base64"
        elif raw_body is not None:
            body = str(raw_body).encode("utf-8")
        if "json" in arguments and arguments.get("json") is not None:
            body = json.dumps(arguments["json"], ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json; charset=utf-8")

        try:
            timeout = min(120.0, max(0.1, float(arguments.get("timeout", 15))))
            max_redirects = min(10, max(0, int(arguments.get("max_redirects", 5))))
            max_bytes = min(10 * 1024 * 1024, max(1024, int(
                arguments.get("max_bytes", MAX_INLINE)
            )))
        except (TypeError, ValueError):
            return "请求失败：timeout / max_redirects / max_bytes 必须是数字"
        follow = bool(arguments.get("follow_redirects", True))
        verify_tls = bool(arguments.get("verify_tls", True))
        proxy = str(arguments.get("proxy") or "").strip()

        save_path = str(arguments.get("save_path") or "").strip()
        limit = MAX_SAVE if save_path else max_bytes
        try:
            result = perform(
                url, method=method, headers=headers, body=body, timeout=timeout,
                follow=follow, max_redirects=max_redirects,
                verify_tls=verify_tls, proxy=proxy, limit=limit,
            )
        except SandboxDenied:
            raise
        except Exception as error:
            return f"请求失败：{error}"

        data = result["body"]
        lines = [
            f"### {method} {url}",
            f"状态：{result['status']} {result['reason'] or ''}".rstrip(),
            f"最终地址：{result['url']}",
            f"耗时：{result['seconds']}s · 响应体：{human_size(len(data))}"
            + ("（已截断）" if result["truncated"] else ""),
        ]
        if len(result["chain"]) > 1:
            chain_text = " → ".join(
                f"{item['status']} {item['url']}" for item in result["chain"]
            )
            lines.append(f"跳转链：{chain_text}")
        else:
            lines.append("跳转链：（无跳转）")
        lines.append("响应头：")
        lines.extend("  " + item for item in _header_lines(result["headers"]))

        if save_path:
            try:
                target = resolve(self.__workdir, save_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
                try:
                    temp.write_bytes(data)
                    os.replace(temp, target)
                finally:
                    try:
                        if temp.exists():
                            temp.unlink()
                    except OSError:
                        pass
            except SandboxDenied:
                raise
            except Exception as error:
                return "\n".join(lines) + f"\n\n保存失败：{error}"
            digest = hashlib.sha256(data).hexdigest()
            lines.append(f"已保存：{target}（{human_size(len(data))}，sha256 {digest}）")
            if result["truncated"]:
                lines.append("注意：达到 64MB 下载上限，文件不完整。")
            return "\n".join(lines)

        if not data:
            lines.append("正文：（空）")
            return "\n".join(lines)

        if _is_text(result["headers"]):
            try:
                text = data.decode(_charset(result["headers"]), errors="replace")
            except LookupError:
                text = data.decode("utf-8", errors="replace")
            if result["truncated"]:
                text += f"\n…（只显示前 {len(data)} 字节）"
            lines.append("正文：")
            lines.append(text)
        else:
            lines.append(
                f"正文：二进制内容（{len(data)} B，未内联）；需要文件时用 save_path 落盘。"
            )
        return "\n".join(lines)
