"""域名收集：证书透明度（crt.sh）+ 主动子域爆破（dnsx）+ 聚合收集。

聚合能力 domainCollect 的链条：
  subfinder（被动多源） → crt.sh（证书透明度） → dnsx 字典爆破 → dnsx 批量解析
每一步单独失败都不影响其余步骤；结果统一写项目资产库和总表。
"""
import json
import re
import time
from pathlib import Path

from .Assets import PROJECT_CSV, add_assets, project_dir
from .Executions import executions
from .Output import CapabilityResult
from .Spec import CapabilitySpec
from .Tools import checked, tool_path

_BUNDLED_WORDS = Path(__file__).resolve().parents[1] / "shell" / "wordlists"

DEFAULT_SUBDOMAIN_WORDLIST = str(
    _BUNDLED_WORDS / "subdomains-top1million-20000.txt"
    if (_BUNDLED_WORDS / "subdomains-top1million-20000.txt").exists()
    else Path(r"D:\wangj\zi_dian\ZD\子域字典\subdomains-top1million-20000.txt")
)
BIG_SUBDOMAIN_WORDLIST = str(
    _BUNDLED_WORDS / "subdomains-top1million-110000.txt"
    if (_BUNDLED_WORDS / "subdomains-top1million-110000.txt").exists()
    else Path(r"D:\wangj\zi_dian\ZD\子域字典\subdomains-top1million-110000.txt")
)
CRT_URL = "https://crt.sh/"
_A_LINE = re.compile(r"^(\S+)\s+\[(A|AAAA|CNAME)\]\s+\[(.+?)\]$")
_WORDLIST_CACHE = {"path": "", "mtime": 0.0, "rows": 0}


def _session():
    execution = executions.current()
    return execution.session_id if execution is not None else ""


def _source(name):
    return {"source": f"{name}（域名收集）", "tool": name}


def _clean_domain(domain):
    return str(domain or "").strip().lower().rstrip(".")


def _under(name, domain):
    name = _clean_domain(name).removeprefix("*.")
    return bool(name) and (name == domain or name.endswith("." + domain))


# ---------- 各数据源（抽成函数，测试可替换） ----------

def subfinder_domains(domain, all_sources=True, timeout=90, cancel=None):
    """subfinder 被动子域；返回域名集合。"""
    if tool_path("subfinder") is None:
        raise RuntimeError("没有找到 subfinder（配置 tools.subfinder 指定路径）")
    args = ["-d", domain, "-silent", "-json"]
    if all_sources:
        args.append("-all")
    out, _ = checked("subfinder", args, timeout, cancel)
    found = set()
    for line in out.splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        host = str(item.get("host") or "").strip()
        if _under(host, domain):
            found.add(_clean_domain(host).removeprefix("*."))
    return found


def _crtsh_get(query, timeout=10):
    import urllib.parse
    import urllib.request

    url = CRT_URL + "?" + urllib.parse.urlencode({"q": query, "output": "json"})
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; Spirit/0.1)"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def crtsh_request(domain, timeout=10):
    """查 crt.sh（证书透明度）；返回原始 JSON 文本。测试里替换这个函数。

    crt.sh 经常 502 / 限流：先带通配符查，失败重试两次，最后退化到裸域名包含匹配。
    """
    last = None
    for _ in range(3):
        try:
            return _crtsh_get(f"%.{domain}", timeout)
        except Exception as error:
            last = error
            time.sleep(1.5)
    try:
        return _crtsh_get(domain, timeout)
    except Exception:
        raise last


def crtsh_domains(domain):
    """解析 crt.sh 返回，得到子域集合。"""
    text = crtsh_request(domain)
    try:
        rows = json.loads(text)
    except Exception as error:
        raise RuntimeError(f"crt.sh 返回不是 JSON（可能被限流）：{error}") from error
    if not isinstance(rows, list):
        raise RuntimeError("crt.sh 返回格式不认识")
    found = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for value in str(row.get("name_value") or "").splitlines():
            value = value.strip()
            if _under(value, domain):
                found.add(_clean_domain(value).removeprefix("*."))
    return found


def dnsx_run(args, timeout=120, cancel=None):
    """执行 dnsx；返回 (标准输出, 是否超时截断)。超时也保留已捕获的输出。

    测试里替换这个函数（返回同样的二元组）。
    """
    from .Executions import ExecutionCancelled
    from .Tools import run as tool_run

    if tool_path("dnsx") is None:
        raise RuntimeError("没有找到 dnsx（配置 tools.dnsx 指定路径）")
    out, err, code, problem = tool_run("dnsx", args, timeout, cancel)
    if problem == "cancelled":
        raise ExecutionCancelled("用户停止")
    if problem == "missing":
        raise RuntimeError(err)
    if problem == "timeout":
        return out, True
    if code not in (0, None):
        raise RuntimeError(f"dnsx 退出码 {code}：{(err or out)[-300:]}")
    return out, False


def _parse_dnsx(text, domain):
    """dnsx -a -cname -resp 的输出 → (ips, cnames)，都是 {域名: [值,...]}。"""
    ips, cnames = {}, {}
    for line in str(text or "").splitlines():
        match = _A_LINE.match(line.strip())
        if not match:
            continue
        name, kind, value = match.groups()
        name = _clean_domain(name)
        if not _under(name, domain):
            continue
        target = cnames if kind == "CNAME" else ips
        values = target.setdefault(name, [])
        value = value.strip()
        if value not in values:
            values.append(value)
    return ips, cnames


def _strip_wildcard(ips, cnames, wild_ips, wild_cnames):
    """过滤泛解析（wildcard DNS）命中：A 记录和 CNAME 都落在泛解析目标上的不算子域。"""
    if not wild_ips and not wild_cnames:
        return {name: list(values) for name, values in ips.items()}
    kept = {}

    def wild(name):
        name_ips = ips.get(name) or []
        name_cnames = cnames.get(name) or []
        ip_wild = bool(wild_ips) and bool(name_ips) and all(v in wild_ips for v in name_ips)
        cname_wild = bool(wild_cnames) and bool(name_cnames) and all(
            v in wild_cnames for v in name_cnames)
        return (not name_ips or ip_wild) and (not name_cnames or cname_wild)

    for name in set(ips) | set(cnames):
        if wild(name):
            continue
        kept[name] = list(ips.get(name) or [])
    return kept


def _random_probes(domain, count=2):
    import secrets

    return [f"spirit-{secrets.token_hex(4)}.{domain}" for _ in range(count)]


def wildcard_targets(domain, threads=20, timeout=30, cancel=None):
    """探泛解析：随机子域的解析结果就是 wildcard 目标。"""
    (ips, cnames), _ = dnsx_resolve_raw(
        _random_probes(domain), domain, threads, timeout, cancel)
    return set(value for values in ips.values() for value in values), \
        set(value for values in cnames.values() for value in values)


def dnsx_brute(domain, wordlist, threads=300, timeout=150, cancel=None, rate=None):
    """dnsx 字典爆破；返回 ({域名: [ip]}, 是否超时截断)，已过滤泛解析。"""
    wordlist = str(wordlist or "").strip() or DEFAULT_SUBDOMAIN_WORDLIST
    if not Path(wordlist).exists():
        raise RuntimeError(f"子域字典不存在：{wordlist}")
    args = [
        "-d", domain, "-w", wordlist,
        "-a", "-cname", "-resp", "-silent", "-nc", "-retry", "3",
        "-t", str(max(1, min(2000, int(threads or 300)))),
    ]
    if rate:
        args += ["-rl", str(max(1, int(rate)))]
    text, partial = dnsx_run(args, timeout, cancel)
    ips, cnames = _parse_dnsx(text, domain)
    try:
        wild_ips, wild_cnames = wildcard_targets(domain, 20, 30, cancel)
    except Exception:
        wild_ips, wild_cnames = set(), set()
    return _strip_wildcard(ips, cnames, wild_ips, wild_cnames), partial


def dnsx_resolve_raw(domains, domain, threads=100, timeout=45, cancel=None):
    """批量解析已有域名；返回 ((ips, cnames), 是否超时截断)。"""
    names = [name for name in dict.fromkeys(domains) if name]
    if not names:
        return ({}, {}), False
    target_dir = project_dir(_session()) / "raw"
    list_file = target_dir / f"dnsx-input-{int(time.time())}.txt"
    list_file.write_text("\n".join(names), encoding="utf-8")
    try:
        args = [
            "-l", str(list_file), "-a", "-cname", "-resp", "-silent", "-nc", "-retry", "3",
            "-t", str(max(1, min(1000, int(threads or 100)))),
        ]
        text, partial = dnsx_run(args, timeout, cancel)
        return _parse_dnsx(text, domain), partial
    finally:
        try:
            list_file.unlink()
        except OSError:
            pass


def dnsx_resolve(domains, domain, threads=100, timeout=45, cancel=None):
    """批量解析已有域名（补 IP，过滤泛解析）；返回 ({域名: [ip]}, 是否超时截断)。"""
    (ips, cnames), partial = dnsx_resolve_raw(domains, domain, threads, timeout, cancel)
    try:
        wild_ips, wild_cnames = wildcard_targets(domain, 20, 30, cancel)
    except Exception:
        wild_ips, wild_cnames = set(), set()
    return _strip_wildcard(ips, cnames, wild_ips, wild_cnames), partial


def wordlist_info(path=None):
    """子域字典状态（给 UI 显示）：路径、是否存在、条数。"""
    target = Path(str(path or "").strip() or DEFAULT_SUBDOMAIN_WORDLIST)
    if not target.exists():
        return {"path": str(target), "exists": False, "rows": 0}
    try:
        mtime = target.stat().st_mtime
    except OSError:
        return {"path": str(target), "exists": False, "rows": 0}
    if _WORDLIST_CACHE["path"] == str(target) and _WORDLIST_CACHE["mtime"] == mtime:
        return {"path": str(target), "exists": True, "rows": _WORDLIST_CACHE["rows"]}
    rows = 0
    try:
        with open(target, encoding="utf-8", errors="ignore") as file:
            rows = sum(1 for _ in file)
    except OSError:
        return {"path": str(target), "exists": False, "rows": 0}
    _WORDLIST_CACHE.update({"path": str(target), "mtime": mtime, "rows": rows})
    return {"path": str(target), "exists": True, "rows": rows}


def _records(found):
    """{域名: [ip]} → 资产记录（每个域名一条，多 IP 用空格分隔）。"""
    records = []
    for name, ips in found.items():
        records.append({
            "domain": name,
            "ip": " ".join(ips) if ips else "",
        })
    return records


def _write(name, records, query):
    added, total = add_assets(_session(), records, source=name, query=query)
    return added, total


# ---------- 能力 ----------

class CrtShCapability:
    name = "crtshSearch"
    description = (
        "查 crt.sh 证书透明度日志，收集证书里出现过的子域名（历史证书，覆盖面常比被动源更广）。"
        "结果写入项目资产库。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "根域名，例如 example.com"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=60)

    def run(self, arguments):
        domain = _clean_domain(arguments.get("domain"))
        if not domain:
            return CapabilityResult("domain 不能为空", _source("crt.sh"), ok=False)
        try:
            found = crtsh_domains(domain)
        except Exception as error:
            return CapabilityResult(f"crt.sh 查询失败：{str(error)[:200]}", _source("crt.sh"), ok=False)
        added, total = _write("crt.sh", _records({name: [] for name in found}),
                              query=f"domain={domain}")
        lines = [f"crt.sh 找到 {len(found)} 个子域，新增 {added} 条，项目共 {total} 条。"]
        lines += [f"- {name}" for name in sorted(found)[:40]]
        if len(found) > 40:
            lines.append(f"…还有 {len(found) - 40} 个")
        if not found:
            lines.append("证书里没有该域名的子域记录。")
        return CapabilityResult("\n".join(lines), _source("crt.sh"))


class SubdomainBruteCapability:
    name = "subdomainBrute"
    description = (
        "用 dnsx + 子域字典做主动爆破（比被动源覆盖更全，需目标 DNS 允许解析）。"
        "默认字典是 SecLists top 20000（约 1 分钟）；要更深可传 "
        "D:\\wangj\\zi_dian\\ZD\\子域字典\\subdomains-top1million-110000.txt。"
        "自动过滤泛解析（wildcard DNS）；命中结果连同解析 IP 写入项目资产库。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "根域名，例如 example.com"},
            "wordlist": {"type": "string", "description": "子域字典；留空用默认 20000 字典"},
            "threads": {"type": "integer", "description": "并发，默认 300"},
            "timeout": {"type": "integer", "description": "秒，默认 150，最大 300"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=330)

    def available(self):
        return tool_path("dnsx") is not None

    def run(self, arguments):
        domain = _clean_domain(arguments.get("domain"))
        if not domain:
            return CapabilityResult("domain 不能为空", _source("dnsx"), ok=False)
        timeout = max(10, min(300, int(arguments.get("timeout") or 150)))
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        try:
            found, partial = dnsx_brute(domain, arguments.get("wordlist"),
                                        arguments.get("threads") or 300, timeout, cancel)
        except Exception as error:
            return CapabilityResult(f"dnsx 爆破失败：{str(error)[:200]}", _source("dnsx"), ok=False)
        added, total = _write("dnsx（爆破）", _records(found),
                              query=f"brute domain={domain}")
        lines = [f"dnsx 爆破 {domain}：命中 {len(found)} 个子域，新增 {added} 条，项目共 {total} 条。"]
        if partial:
            lines.append("⚠️ 字典没跑完就超时了：下面是已命中的部分结果，可以调大 timeout 再补。")
        lines += [f"- {name} {','.join(ips)}".rstrip() for name, ips in sorted(found.items())[:40]]
        if len(found) > 40:
            lines.append(f"…还有 {len(found) - 40} 个")
        if not found:
            lines.append("字典跑完没有命中；换字典或确认目标 DNS 是否可解析。")
        return CapabilityResult("\n".join(lines), _source("dnsx"))


class DomainCollectCapability:
    name = "domainCollect"
    description = (
        "本地域名收集（前提是测绘平台结果不够）：subfinder 被动源 + crt.sh 证书透明度 + "
        "dnsx 字典爆破，再用 dnsx 批量解析补 IP，合并去重写项目资产库。"
        "自动过滤泛解析（wildcard DNS）；默认 20000 字典约 2–3 分钟，可指定 110000 字典更深（5 分钟上限）。"
        "任何一步失败不影响其它步骤（输出里会标出失败的那步）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "根域名，例如 example.com"},
            "brute": {"type": "boolean", "description": "是否做字典爆破，默认 true"},
            "wordlist": {"type": "string", "description": "子域字典；留空用默认 20000 字典"},
            "threads": {"type": "integer", "description": "dnsx 并发，默认 300"},
        },
        "required": ["domain"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(self.name, self.description, self.parameters,
                              side_effect="external", trust="untrusted", timeout=360)

    def run(self, arguments):
        domain = _clean_domain(arguments.get("domain"))
        if not domain:
            return CapabilityResult("domain 不能为空", _source("domainCollect"), ok=False)
        execution = executions.current()
        cancel = execution.cancel if execution is not None else None
        threads = max(1, min(2000, int(arguments.get("threads") or 300)))
        started = time.time()
        passive, certs, brute = set(), set(), {}
        notes = []

        try:
            passive = subfinder_domains(domain, True, 90, cancel)
            notes.append(f"subfinder：{len(passive)} 个")
        except Exception as error:
            notes.append(f"subfinder：失败（{str(error)[:200]}）")
        try:
            certs = crtsh_domains(domain)
            notes.append(f"crt.sh：{len(certs)} 个")
        except Exception as error:
            notes.append(f"crt.sh：失败（{str(error)[:200]}）")
        if arguments.get("brute", True):
            try:
                brute, brute_partial = dnsx_brute(
                    domain, arguments.get("wordlist"), threads, 150, cancel)
                notes.append(
                    f"dnsx 爆破：{len(brute)} 个（已过滤泛解析"
                    + ("，超时截断" if brute_partial else "") + "）")
            except Exception as error:
                notes.append(f"dnsx 爆破：失败（{str(error)[:200]}）")

        known = set(passive) | set(certs) | set(brute)
        missing = [name for name in known if name not in brute]
        resolved = {}
        if missing:
            try:
                resolved, resolve_partial = dnsx_resolve(missing, domain, threads, 45, cancel)
                notes.append(
                    f"dnsx 解析：{len(resolved)} 个有记录"
                    + ("（超时截断）" if resolve_partial else ""))
            except Exception as error:
                notes.append(f"dnsx 解析：失败（{str(error)[:200]}）")

        merged = {}
        for name in passive:
            merged[name] = list((resolved.get(name) or []))
        for name in certs:
            merged.setdefault(name, [])
            for ip in resolved.get(name) or []:
                if ip not in merged[name]:
                    merged[name].append(ip)
        for name, ips in brute.items():
            merged[name] = ips

        added_by_source = {}
        if passive:
            added, _ = _write("subfinder", _records({n: resolved.get(n) or [] for n in passive}),
                              query=f"domain={domain}")
            added_by_source["subfinder"] = added
        if certs:
            added, _ = _write("crt.sh", _records({n: resolved.get(n) or [] for n in certs}),
                              query=f"domain={domain}")
            added_by_source["crt.sh"] = added
        if brute:
            added, _ = _write("dnsx（爆破）", _records(brute), query=f"brute domain={domain}")
            added_by_source["dnsx"] = added

        total = len(merged)
        elapsed = int((time.time() - started) * 1000)
        lines = [f"域名收集 {domain}：共 {total} 个域名，用时 {elapsed}ms。"]
        lines += [f"- {note}" for note in notes]
        if merged:
            sample = sorted(merged)[:30]
            lines.append("域名（前 30）：")
            lines += [f"  {name}" for name in sample]
            if total > 30:
                lines.append(f"  …还有 {total - 30} 个")
        else:
            lines.append("所有来源都没有拿到域名：检查网络 / DNS / 字典，或换测绘平台。")
        lines.append(f"项目总表：{project_dir(_session()) / PROJECT_CSV}")
        ok = bool(merged)
        return CapabilityResult("\n".join(lines), _source("domainCollect"), ok=ok)
