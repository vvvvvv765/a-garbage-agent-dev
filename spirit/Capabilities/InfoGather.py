"""
信息收集能力：DNS / 端口 / HTTP 探活。

三个都是“只读侦察”，不写目标、不改本机状态；结果可能来自外部（trust=untrusted）。
端口扫描走 TCP connect，不依赖 nmap；DNS 用 dnspython，可指定解析服务器。
"""
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import dns.exception
import dns.reversename
import dns.resolver

from .Executions import executions
from .Files import human_size
from .HttpRequest import DEFAULT_UA, perform
from .Spec import CapabilitySpec

DNS_TYPES = ("A", "AAAA", "CNAME", "MX", "NS", "TXT", "SOA", "CAA", "SRV", "PTR")
DNS_ALL = ("A", "AAAA", "CNAME", "MX", "NS", "TXT")
TOP_PORTS = (
    7, 9, 13, 21, 22, 23, 25, 26, 37, 53, 79, 80, 81, 88, 106, 110, 111, 113,
    119, 135, 139, 143, 144, 179, 199, 389, 427, 443, 444, 445, 465, 500, 512,
    513, 514, 515, 520, 523, 524, 540, 548, 554, 556, 563, 587, 593, 623, 626,
    631, 636, 646, 873, 990, 993, 995, 1025, 1026, 1027, 1028, 1029, 1110,
    1433, 1720, 1723, 1755, 1900, 2000, 2001, 2049, 2121, 2717, 3000, 3128,
    3306, 3389, 3986, 4899, 5000, 5009, 5051, 5060, 5101, 5190, 5357, 5432,
    5631, 5666, 5800, 5900, 6000, 6379, 7000, 7070, 8000, 8008, 8009, 8080,
    8081, 8443, 8888, 9000, 9090, 9200, 10000, 27017,
)


def _resolver(server="", timeout=5.0):
    resolver = dns.resolver.Resolver(configure=not bool(server))
    if server:
        resolver.nameservers = [server]
    resolver.timeout = max(0.2, float(timeout))
    resolver.lifetime = max(0.5, float(timeout))
    return resolver


def _answer_text(answer):
    rdtype = answer.rdtype
    if rdtype == dns.rdatatype.MX:
        return f"{answer.preference} {answer.exchange}"
    if rdtype == dns.rdatatype.SOA:
        return (
            f"{answer.mname} {answer.rname} serial={answer.serial} "
            f"refresh={answer.refresh} retry={answer.retry} expire={answer.expire}"
        )
    if rdtype == dns.rdatatype.CAA:
        return f'{answer.flags} {answer.tag} "{answer.value}"'
    if rdtype == dns.rdatatype.SRV:
        return f"{answer.priority} {answer.weight} {answer.port} {answer.target}"
    if rdtype == dns.rdatatype.TXT:
        parts = getattr(answer, "strings", None) or []
        return "".join(part.decode("utf-8", errors="replace") for part in parts)
    target = getattr(answer, "target", None)
    if target is not None:
        return str(target)
    return str(answer)


class DnsLookupCapability:
    name = "dnsLookup"
    description = (
        "查 DNS 记录：A / AAAA / CNAME / MX / NS / TXT / SOA / CAA / SRV / PTR。"
        "record 可写一个类型、逗号分隔多个，或 all；PTR 时 domain 传 IP。"
        "可指定 DNS 服务器（server），方便对比不同解析。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "域名；查 PTR 时传 IP"},
            "record": {
                "type": "string",
                "description": "记录类型，默认 A；可 all 或 A,AAAA,MX",
            },
            "server": {"type": "string", "description": "可选 DNS 服务器 IP"},
            "timeout": {"type": "number", "description": "查询超时秒数，默认 5"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters,
            trust="untrusted", side_effect="external", timeout=60,
        )

    def run(self, arguments):
        domain = str(arguments.get("domain") or "").strip().rstrip(".")
        if not domain:
            return "查询失败：domain 不能为空"
        raw_record = str(arguments.get("record") or "A").strip()
        if raw_record.lower() == "all":
            records = list(DNS_ALL)
        else:
            records = [item.strip().upper() for item in raw_record.split(",") if item.strip()]
        bad = [item for item in records if item not in DNS_TYPES]
        if bad:
            return f"查询失败：不支持的记录类型 {', '.join(bad)}（可选 {', '.join(DNS_TYPES)}）"
        if not records:
            return "查询失败：record 不能为空"
        server = str(arguments.get("server") or "").strip()
        try:
            timeout = min(30.0, max(0.2, float(arguments.get("timeout", 5))))
        except (TypeError, ValueError):
            return "查询失败：timeout 必须是数字"
        resolver = _resolver(server, timeout)

        lines = [f"### DNS {domain}" + (f" @ {server}" if server else "")]
        for record in records:
            executions.check()
            query = domain
            try:
                if record == "PTR":
                    query = dns.reversename.from_address(domain)
                answers = resolver.resolve(query, record, lifetime=timeout)
            except dns.resolver.NXDOMAIN:
                lines.append(f"{record}：域名不存在")
                continue
            except dns.resolver.NoAnswer:
                lines.append(f"{record}：（无记录）")
                continue
            except (dns.resolver.NoNameservers, dns.exception.Timeout) as error:
                if server:
                    lines.append(f"{record}：查询失败（{error}）")
                    continue
                # 系统 DNS 常被 VPN / 虚拟网卡带坏：自动回退公共 DNS 再试一次
                try:
                    answers = _resolver("223.5.5.5", timeout).resolve(
                        query, record, lifetime=timeout)
                    lines.append(f"{record}：（系统 DNS 失败，已回退 223.5.5.5）")
                except Exception:
                    lines.append(f"{record}：查询失败（{error}）")
                    continue
            except (ValueError, dns.exception.DNSException) as error:
                lines.append(f"{record}：查询失败（{error}）")
                continue
            else:
                lines.append(f"{record}：")
            try:
                for answer in answers:
                    lines.append(f"  - {_answer_text(answer)}（TTL {answers.rrset.ttl}）")
            except Exception:
                lines.append(f"  - {answers}")
        return "\n".join(lines)


def _parse_ports(raw):
    text = str(raw or "").strip().lower()
    if not text or text == "top":
        return list(TOP_PORTS)
    if text == "all":
        return list(range(1, 65536))
    ports = set()
    for piece in re.split(r"[,\s]+", text):
        if not piece:
            continue
        if "-" in piece:
            start, _, end = piece.partition("-")
            try:
                start, end = int(start), int(end)
            except ValueError:
                raise ValueError(f"端口范围不合法：{piece}")
            if start > end:
                start, end = end, start
            if start < 1 or end > 65535:
                raise ValueError(f"端口范围超出 1-65535：{piece}")
            ports.update(range(start, end + 1))
        else:
            try:
                port = int(piece)
            except ValueError:
                raise ValueError(f"端口不合法：{piece}")
            if port < 1 or port > 65535:
                raise ValueError(f"端口超出 1-65535：{port}")
            ports.add(port)
    return sorted(ports)


def _service(port):
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return ""


def _connect(host, port, timeout, family=socket.AF_INET):
    executions.check()
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        code = sock.connect_ex((host, port))
    finally:
        sock.close()
    return code == 0


class PortScanCapability:
    name = "portScan"
    description = (
        "TCP connect 端口扫描（不依赖 nmap）：ports 支持 22,80,443 / 1-1024 / top / all。"
        "返回开放端口和服务名；只发起连接，不发业务数据。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "域名或 IP"},
            "ports": {"type": "string", "description": "端口，默认 top（约 100 个）"},
            "timeout": {"type": "number", "description": "每个端口超时秒数，默认 0.8"},
            "concurrency": {"type": "integer", "description": "并发数，默认 128，上限 256"},
        },
        "required": ["host"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters,
            trust="untrusted", side_effect="external", timeout=120, max_inline=5000,
        )

    def run(self, arguments):
        raw_host = str(arguments.get("host") or "").strip()
        if not raw_host:
            return "扫描失败：host 不能为空"
        if "://" in raw_host:
            from urllib.parse import urlparse
            raw_host = urlparse(raw_host).hostname or ""
        host = raw_host.strip("[]")
        try:
            ports = _parse_ports(arguments.get("ports"))
            timeout = min(10.0, max(0.1, float(arguments.get("timeout", 0.8))))
            concurrency = min(256, max(1, int(arguments.get("concurrency", 128))))
        except (TypeError, ValueError) as error:
            return f"扫描失败：{error}"
        try:
            infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            return f"扫描失败：解析不了 {host}（{error}）"
        addresses = []
        families = {}
        for info in infos:
            address = info[4][0]
            families.setdefault(address, info[0])
            if address not in addresses:
                addresses.append(address)
        ipv4 = [item for item in addresses if families.get(item) == socket.AF_INET]
        target = (ipv4 or addresses)[0]
        family = families.get(target, socket.AF_INET)
        started = time.monotonic()
        opened = []
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(_connect, target, port, timeout, family): port
                for port in ports
            }
            try:
                for future in as_completed(futures):
                    port = futures[future]
                    executions.check()
                    try:
                        if future.result():
                            opened.append(port)
                    except Exception:
                        continue
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        opened.sort()
        elapsed = round(time.monotonic() - started, 2)
        lines = [
            f"### 端口扫描 {host} ({', '.join(addresses[:5])})",
            f"端口：{len(ports)} 个 · 并发 {concurrency} · 超时 {timeout}s · 耗时 {elapsed}s",
            f"开放：{len(opened)} 个",
        ]
        for port in opened:
            service = _service(port)
            lines.append(f"  {port}/tcp" + (f"  {service}" if service else ""))
        if not opened:
            lines.append("  （没有开放端口）")
        return "\n".join(lines)


def _title(body, charset="utf-8"):
    match = re.search(rb"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    try:
        text = match.group(1).decode(charset, errors="replace")
    except LookupError:
        text = match.group(1).decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:120]


class HttpProbeCapability:
    name = "httpProbe"
    description = (
        "批量探活 URL：返回状态码、最终地址、标题、Server、Content-Type、大小和耗时。"
        "适合先摸清一批站点 / 路径，再决定用 httpRequest 深挖。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URL 列表；最多 50 个",
            },
            "timeout": {"type": "number", "description": "每个 URL 超时秒数，默认 10"},
            "follow_redirects": {"type": "boolean", "description": "默认 true"},
            "verify_tls": {"type": "boolean", "description": "默认 true"},
            "proxy": {"type": "string", "description": "可选代理"},
        },
        "required": ["urls"],
        "additionalProperties": False,
    }

    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            self.name, self.description, self.parameters,
            trust="untrusted", side_effect="external", timeout=120, max_inline=6000,
        )

    def run(self, arguments):
        urls = arguments.get("urls")
        if isinstance(urls, str):
            urls = re.split(r"[,\s]+", urls)
        if not isinstance(urls, list):
            return "探活失败：urls 必须是 URL 列表"
        urls = [str(item).strip() for item in urls if str(item).strip()][:50]
        if not urls:
            return "探活失败：urls 为空"
        try:
            timeout = min(60.0, max(0.5, float(arguments.get("timeout", 10))))
        except (TypeError, ValueError):
            return "探活失败：timeout 必须是数字"
        follow = bool(arguments.get("follow_redirects", True))
        verify_tls = bool(arguments.get("verify_tls", True))
        proxy = str(arguments.get("proxy") or "").strip()
        lines = [f"### HTTP 探活（{len(urls)} 个）"]
        for url in urls:
            executions.check()
            try:
                result = perform(
                    url, "GET",
                    headers={"User-Agent": DEFAULT_UA, "Accept": "*/*"},
                    timeout=timeout, follow=follow, max_redirects=5,
                    verify_tls=verify_tls, proxy=proxy, limit=512 * 1024,
                )
            except Exception as error:
                lines.append(f"- {url}：失败（{error}）")
                continue
            try:
                content_type = result["headers"].get("Content-Type") or ""
                server = result["headers"].get("Server") or ""
            except Exception:
                content_type, server = "", ""
            match = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
            charset = match.group(1) if match else "utf-8"
            title = _title(result["body"], charset)
            extra = []
            if server:
                extra.append(f"server={server[:60]}")
            if content_type:
                extra.append(content_type.split(";", 1)[0].strip())
            if title:
                extra.append(f"title={title}")
            lines.append(
                f"- {url} → {result['status']} {result['url']} "
                f"({human_size(len(result['body']))}, {result['seconds']}s) "
                + " ".join(extra)
            )
        return "\n".join(lines)
