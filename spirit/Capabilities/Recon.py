"""外部侦察能力：subfinder / ffuf / naabu（统一写入项目资产库）。"""
import json
import os
import tempfile
import time
from pathlib import Path

from .Assets import PROJECT_CSV, add_assets, project_dir
from .Executions import executions
from .Output import CapabilityResult
from .Spec import CapabilitySpec
from .Tools import checked, tool_path

_BUNDLED_WORDS = Path(__file__).resolve().parents[1] / "shell" / "wordlists"
DEFAULT_WORDLIST = str(
    _BUNDLED_WORDS / "传统-目录.txt"
    if (_BUNDLED_WORDS / "传统-目录.txt").exists()
    else Path(r"D:\wangj\zi_dian\ZD\网站目录结构字典\传统-目录.txt")
)
_WORDLIST_ROWS = {}


def _wordlist_rows(path):
    """字典行数（带缓存）；读不了返回 0。"""
    key = str(path)
    try:
        stamp = Path(path).stat().st_mtime
    except OSError:
        return 0
    cached = _WORDLIST_ROWS.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    rows = 0
    try:
        with open(path, encoding="utf-8", errors="ignore") as file:
            rows = sum(1 for _ in file)
    except OSError:
        return 0
    _WORDLIST_ROWS[key] = (stamp, rows)
    return rows


def _session():
    execution = executions.current()
    return execution.session_id if execution is not None else ""


def _source(name):
    return {"source": f"{name}（外部工具）", "tool": name}


def _result(name, session_id, records, summary, query, raw=None):
    added, total = add_assets(session_id, records, source=name, query=query, raw=raw)
    lines = [
        summary,
        f"新增 {added} 条，项目资产库共 {total} 条。",
        f"项目总表：{project_dir(session_id) / PROJECT_CSV}",
    ]
    if not records:
        lines.append("没有发现记录；检查目标 / 字典 / 端口范围，或换一个工具再试。")
    return CapabilityResult("\n".join(lines), _source(name))


class SubfinderCapability:
    name = "subfinderEnum"
    description = (
        "用 subfinder 被动收集子域名（公开数据源，不发探测包）。"
        "完整结果写入项目资产库；没有记录不代表没有子域，可能只是源里没有。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "根域名，例如 example.com"},
            "all": {"type": "boolean", "description": "使用全部数据源（更慢）"},
            "timeout": {"type": "integer", "description": "秒，默认 120，最大 600"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=330)

    def available(self):
        return tool_path("subfinder") is not None

    def run(self, arguments):
        if not self.available():
            return CapabilityResult("没有找到 subfinder（配置 tools.subfinder 指定路径）",
                                    _source("subfinder"), ok=False)
        domain = str(arguments.get("domain") or "").strip()
        if not domain:
            return CapabilityResult("domain 不能为空", _source("subfinder"), ok=False)
        timeout = max(1, min(300, int(arguments.get("timeout") or 90)))
        args = ["-d", domain, "-silent", "-json"]
        if arguments.get("all"):
            args.append("-all")
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            out, _ = checked("subfinder", args, timeout, cancel)
        except Exception as error:
            return CapabilityResult(f"subfinder 失败：{error}", _source("subfinder"), ok=False)
        records = []
        for line in out.splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            host = str(item.get("host") or "").strip()
            if host:
                records.append({"domain": host.removeprefix("*."), "host": host})
        return _result("subfinder", _session(), records,
                       f"subfinder 枚举 {domain}：找到 {len(records)} 个子域名。",
                       f"domain={domain}")


class FfufCapability:
    name = "ffufScan"
    description = (
        "用 ffuf 做 Web 目录 / 路径 fuzz。URL 里用 FUZZ 标记位置；"
        "结果自动写入项目资产库，只把命中摘要返回给你。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "含 FUZZ 的 URL，例如 https://a.com/FUZZ"},
            "wordlist": {"type": "string", "description": "字典路径；留空用默认目录字典"},
            "method": {"type": "string", "description": "HTTP 方法，默认 GET"},
            "headers": {"type": "object", "description": "额外请求头"},
            "filter_status": {"type": "string", "description": "过滤状态码，例如 404,403"},
            "auto_calibrate": {"type": "boolean", "description": "自动校准、过滤通配假命中，默认 true"},
            "threads": {"type": "integer", "description": "并发，默认 40"},
            "timeout": {"type": "integer", "description": "秒，默认 180，最大 600"},
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=330)

    def available(self):
        return tool_path("ffuf") is not None

    def run(self, arguments):
        if not self.available():
            return CapabilityResult("没有找到 ffuf（配置 tools.ffuf 指定路径）",
                                    _source("ffuf"), ok=False)
        url = str(arguments.get("url") or "").strip()
        if "FUZZ" not in url:
            return CapabilityResult("url 必须包含 FUZZ 占位符", _source("ffuf"), ok=False)
        wordlist = str(arguments.get("wordlist") or DEFAULT_WORDLIST).strip()
        if not Path(wordlist).exists():
            return CapabilityResult(f"字典不存在：{wordlist}", _source("ffuf"), ok=False)
        timeout = max(1, min(300, int(arguments.get("timeout") or 180)))
        threads = max(1, min(200, int(arguments.get("threads") or 40)))
        # 大字典按条数估时：线程 × 3 req/s 是 HTTPS 实测的保守值；
        # 估算超时就把 timeout 自动抬到够用（仍不超过 300 秒），避免白跑满超时。
        rows = _wordlist_rows(wordlist)
        note = ""
        if rows:
            estimate = rows / max(1, threads * 3)
            if estimate > timeout:
                adjusted = min(300, int(estimate * 1.3) + 15)
                if adjusted > timeout:
                    note = (f"字典 {rows} 条 / {threads} 线程，预计约 {int(estimate)} 秒，"
                            f"timeout 已从 {timeout} 调到 {adjusted} 秒。\n")
                    timeout = adjusted
        session_id = _session()
        output = project_dir(session_id) / "raw" / f"ffuf-{int(time.time())}.json"
        args = [
            "-u", url, "-w", wordlist, "-of", "json", "-o", str(output),
            "-s", "-noninteractive",
            "-t", str(threads),
        ]
        # 自动校准：先探基线响应，过滤“所有路径都一样”的假命中（301 全命中、通配 200 等）
        if arguments.get("auto_calibrate", True):
            args.append("-ac")
        method = str(arguments.get("method") or "").strip().upper()
        if method:
            args += ["-X", method]
        if arguments.get("filter_status"):
            args += ["-fc", str(arguments["filter_status"])]
        headers = arguments.get("headers") or {}
        if isinstance(headers, dict):
            for key, value in headers.items():
                args += ["-H", f"{key}: {value}"]
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            checked("ffuf", args, timeout, cancel)
        except Exception as error:
            return CapabilityResult(f"ffuf 失败：{error}", _source("ffuf"), ok=False)
        if not output.exists():
            return CapabilityResult("ffuf 没有生成输出文件", _source("ffuf"), ok=False)
        try:
            data = json.loads(output.read_text(encoding="utf-8"))
        except Exception as error:
            return CapabilityResult(f"ffuf 输出解析失败：{error}", _source("ffuf"), ok=False)
        records = []
        for item in data.get("results") or []:
            target = str(item.get("url") or "").strip()
            if not target:
                continue
            records.append({
                "url": target, "host": item.get("host") or "",
                "title": f"HTTP {item.get('status')} · {item.get('length')} bytes",
                "server": item.get("content_type") or "",
            })
        result = _result("ffuf", session_id, records,
                         f"ffuf {url}：命中 {len(records)} 个路径。",
                         f"url={url} wordlist={wordlist}", raw=data)
        if note:
            return CapabilityResult(note + result.content, result.meta, ok=result.ok)
        return result


class NaabuCapability:
    name = "naabuScan"
    description = (
        "用 naabu 做端口扫描（TCP connect，不需要管理员权限）。"
        "结果写入项目资产库；默认扫 top 100 端口。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "域名或 IP"},
            "top_ports": {"type": "integer", "description": "top N 端口，默认 100"},
            "ports": {"type": "string", "description": "自定义端口，例如 22,80,443 或 1-1024"},
            "rate": {"type": "integer", "description": "包速率，默认 1000"},
            "timeout": {"type": "integer", "description": "秒，默认 180，最大 600"},
        },
        "required": ["host"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=330)

    def available(self):
        return tool_path("naabu") is not None

    def run(self, arguments):
        if not self.available():
            return CapabilityResult("没有找到 naabu（配置 tools.naabu 指定路径）",
                                    _source("naabu"), ok=False)
        host = str(arguments.get("host") or "").strip()
        if not host:
            return CapabilityResult("host 不能为空", _source("naabu"), ok=False)
        timeout = max(1, min(300, int(arguments.get("timeout") or 180)))
        args = ["-host", host, "-silent", "-json",
                "-rate", str(max(1, int(arguments.get("rate") or 1000)))]
        if arguments.get("ports"):
            args += ["-p", str(arguments["ports"])]
        else:
            args += ["-top-ports", str(max(1, min(65535, int(arguments.get("top_ports") or 100))))]
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            out, _ = checked("naabu", args, timeout, cancel)
        except Exception as error:
            return CapabilityResult(f"naabu 失败：{error}", _source("naabu"), ok=False)
        records = []
        for line in out.splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            ip = str(item.get("ip") or item.get("host") or host)
            port = item.get("port")
            records.append({"ip": ip, "host": host if host != ip else "", "port": port,
                            "protocol": item.get("protocol") or "tcp"})
        return _result("naabu", _session(), records,
                       f"naabu 扫描 {host}：开放 {len(records)} 个端口。",
                       f"host={host} ports={arguments.get('ports') or 'top' + str(arguments.get('top_ports') or 100)}")
