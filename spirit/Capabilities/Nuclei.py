"""漏洞验证：nuclei 模板扫描 + gau 历史 URL。结果都写项目资产库。"""
import json
import time
from pathlib import Path

from .Assets import PROJECT_CSV, add_assets, project_dir
from .Executions import ExecutionCancelled, executions
from .Output import CapabilityResult
from .Spec import CapabilitySpec
from .Tools import run as tool_run, tool_path

_BUNDLED_TEMPLATES = Path(__file__).resolve().parents[1] / "shell" / "nuclei-templates"
DEFAULT_TEMPLATES = str(
    _BUNDLED_TEMPLATES if _BUNDLED_TEMPLATES.is_dir()
    else Path(r"D:\kaifa\tools\nuclei-templates")
)
DEFAULT_SEVERITY = "critical,high,medium"


def _session():
    execution = executions.current()
    return execution.session_id if execution is not None else ""


def _source(name):
    return {"source": f"{name}（外部工具）", "tool": name}


def _run_partial(name, args, timeout=300, cancel=None):
    """跑外部工具；超时也返回已捕获输出，返回 (stdout, 是否超时)。"""
    out, err, code, problem = tool_run(name, args, timeout, cancel)
    if problem == "cancelled":
        raise ExecutionCancelled("用户停止")
    if problem == "missing":
        raise RuntimeError(err)
    if problem == "timeout":
        return out, True
    if code not in (0, None):
        raise RuntimeError(f"{name} 退出码 {code}：{(err or out)[-300:]}")
    return out, False


class NucleiScanCapability:
    name = "nucleiScan"
    description = (
        "用 nuclei 模板做漏洞验证 / POC 扫描（授权范围内）。"
        "默认扫 critical/high/medium；可指定 severity / tags / 模板目录。"
        "结果写入项目资产库（模板名 + 严重级 + 命中地址）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "URL 或 host，例如 https://a.example.com"},
            "severity": {"type": "string",
                         "description": "严重级，逗号分隔；默认 critical,high,medium"},
            "tags": {"type": "string", "description": "模板标签，逗号分隔（可选）"},
            "templates": {"type": "string", "description": "模板目录；留空用默认目录"},
            "rate_limit": {"type": "integer", "description": "每秒请求数，默认 150"},
            "timeout": {"type": "integer", "description": "秒，默认 120，最大 300"},
        },
        "required": ["target"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=330)

    def available(self):
        return tool_path("nuclei") is not None and Path(DEFAULT_TEMPLATES).exists()

    def run(self, arguments):
        if tool_path("nuclei") is None:
            return CapabilityResult("没有找到 nuclei（配置 tools.nuclei 指定路径）",
                                    _source("nuclei"), ok=False)
        target = str(arguments.get("target") or "").strip()
        if not target:
            return CapabilityResult("target 不能为空", _source("nuclei"), ok=False)
        templates = str(arguments.get("templates") or "").strip() or DEFAULT_TEMPLATES
        if not Path(templates).exists():
            return CapabilityResult(f"nuclei 模板目录不存在：{templates}", _source("nuclei"), ok=False)
        severity = str(arguments.get("severity") or "").strip() or DEFAULT_SEVERITY
        timeout = max(10, min(300, int(arguments.get("timeout") or 240)))
        args = [
            "-u", target, "-t", templates, "-jsonl", "-silent", "-nc",
            "-severity", severity,
            "-rl", str(max(1, min(1000, int(arguments.get("rate_limit") or 150)))),
        ]
        tags = str(arguments.get("tags") or "").strip()
        if tags:
            args += ["-tags", tags]
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            out, partial = _run_partial("nuclei", args, timeout, cancel)
        except Exception as error:
            return CapabilityResult(f"nuclei 失败：{str(error)[:300]}", _source("nuclei"), ok=False)
        findings = []
        for line in out.splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            info = item.get("info") or {}
            findings.append({
                "name": info.get("name") or item.get("template-id") or "",
                "severity": str(info.get("severity") or "").lower(),
                "template": item.get("template-id") or "",
                "url": item.get("matched-at") or item.get("host") or target,
            })
        records = [{
            "url": item["url"],
            "title": f"{item['name']} [{item['severity']}]",
            "server": f"nuclei/{item['template']}",
        } for item in findings]
        added, total = add_assets(_session(), records, source="nuclei",
                                  query=f"target={target} sev={severity}")
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        findings.sort(key=lambda item: order.get(item["severity"], 9))
        lines = [
            f"nuclei 扫描 {target}：命中 {len(findings)} 个，新增 {added} 条，项目共 {total} 条。"
        ]
        if partial:
            lines.append("⚠️ 扫描超时截断：以下是已命中的部分结果，可调大 timeout 再补。")
        for item in findings[:30]:
            lines.append(f"- [{item['severity']}] {item['name']} @ {item['url']}")
        if len(findings) > 30:
            lines.append(f"…还有 {len(findings) - 30} 条")
        if not findings:
            lines.append("没有命中；确认目标可达，或换 severity / tags 再试。")
        lines.append(f"项目总表：{project_dir(_session()) / PROJECT_CSV}")
        return CapabilityResult("\n".join(lines), _source("nuclei"))


class GauUrlsCapability:
    name = "gauUrls"
    description = (
        "用 gau 拉取 Wayback / Common Crawl 等历史 URL（含子域），"
        "适合找带参数的老接口。结果写入项目资产库，返回去重摘要。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "根域名，例如 example.com"},
            "subs": {"type": "boolean", "description": "包含子域，默认 true"},
            "providers": {"type": "string", "description": "数据源，默认 wayback,commoncrawl,otx,urlscan"},
            "timeout": {"type": "integer", "description": "秒，默认 120，最大 300"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=330)

    def available(self):
        return tool_path("gau") is not None

    def run(self, arguments):
        if tool_path("gau") is None:
            return CapabilityResult("没有找到 gau（配置 tools.gau 指定路径）",
                                    _source("gau"), ok=False)
        domain = str(arguments.get("domain") or "").strip().lower()
        if not domain:
            return CapabilityResult("domain 不能为空", _source("gau"), ok=False)
        timeout = max(10, min(300, int(arguments.get("timeout") or 120)))
        providers = str(arguments.get("providers") or "").strip()
        args = [domain]
        if arguments.get("subs", True):
            args.append("--subs")
        if providers:
            args += ["--providers", providers]
        args += ["--timeout", "20"]
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            out, partial = _run_partial("gau", args, timeout, cancel)
        except Exception as error:
            return CapabilityResult(f"gau 失败：{str(error)[:300]}", _source("gau"), ok=False)
        urls, seen = [], set()
        for line in out.splitlines():
            url = line.strip()
            if not url.startswith(("http://", "https://")):
                continue
            url = url.split("#")[0]
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        records = [{"url": url, "host": domain} for url in urls[:5000]]
        added, total = add_assets(_session(), records, source="gau",
                                  query=f"domain={domain}")
        lines = [
            f"gau {domain}：历史 URL {len(seen)} 条（已去重），写入 {len(records)} 条，"
            f"新增 {added}，项目共 {total} 条。"
        ]
        if partial:
            lines.append("⚠️ 拉取超时截断：下面是已拿到的部分结果，可调大 timeout 再补。")
        with_params = [url for url in urls if "?" in url]
        for url in with_params[:20]:
            lines.append(f"- {url}")
        if len(with_params) > 20:
            lines.append(f"…还有 {len(with_params) - 20} 条带参数的 URL")
        if not with_params:
            lines.append("历史里没有带参数的 URL；可以换 domain 或换数据源再试。")
        lines.append(f"项目总表：{project_dir(_session()) / PROJECT_CSV}")
        return CapabilityResult("\n".join(lines), _source("gau"))
