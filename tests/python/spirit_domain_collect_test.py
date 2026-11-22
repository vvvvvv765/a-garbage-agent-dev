"""域名收集：crt.sh 解析 / dnsx 爆破与解析 / domainCollect 聚合写资产。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
home = Path(tempfile.mkdtemp(prefix="spirit-domain-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-domain-work-"))
os.environ["SPIRIT_HOME"] = str(home)
os.environ["SPIRIT_WORKDIR"] = str(work)
os.environ["SPIRIT_SESSION_DIR"] = str(home)

from Capabilities import Assets, DomainCollect  # noqa: E402
from Render import render  # noqa: E402

render.set_console(False)

# ---------- 1. crt.sh 解析 ----------
CRT_JSON = json.dumps([
    {"name_value": "example.com\nwww.example.com", "common_name": "example.com"},
    {"name_value": "*.api.example.com", "common_name": "*.api.example.com"},
    {"name_value": "evil-example.com\nexample.com.evil.net", "common_name": "evil"},
])
DomainCollect.crtsh_request = lambda domain, timeout=25: CRT_JSON
found = DomainCollect.crtsh_domains("example.com")
assert found == {"example.com", "www.example.com", "api.example.com"}, found
print("1. crt.sh 解析（去通配 / 过滤超集）ok")

# ---------- 2. dnsx 输出解析 ----------
DNSX_OUT = "\n".join([
    "example.com [A] [1.2.3.4]",
    "www.example.com [A] [5.6.7.8]",
    "www.example.com [CNAME] [cdn.example.com]",
    "notexample.com [A] [9.9.9.9]",
    "bad line here",
])
parsed_ips, parsed_cnames = DomainCollect._parse_dnsx(DNSX_OUT, "example.com")
assert parsed_ips["example.com"] == ["1.2.3.4"], parsed_ips
assert parsed_ips["www.example.com"] == ["5.6.7.8"], parsed_ips
assert parsed_cnames["www.example.com"] == ["cdn.example.com"], parsed_cnames
assert "notexample.com" not in parsed_ips, parsed_ips
print("2. dnsx 输出解析 ok")

# ---------- 3. dnsx 爆破参数 / 临时字典 ----------
wordlist = home / "subs.txt"
wordlist.write_text("www\nmail\napi\n", encoding="utf-8")
calls = []


def fake_dnsx(args, timeout=300, cancel=None):
    calls.append(list(args))
    if "-d" in args:
        return "www.example.com [A] [10.0.0.1]\napi.example.com [A] [10.0.0.2]", False
    listing = Path(args[args.index("-l") + 1]).read_text(encoding="utf-8")
    if "spirit-" in listing:      # 泛解析探测：没有 wildcard
        return "", False
    return "a.example.com [A] [10.0.0.3]", False


DomainCollect.dnsx_run = fake_dnsx
brute, partial = DomainCollect.dnsx_brute("example.com", str(wordlist), threads=50, timeout=60)
assert set(brute) == {"www.example.com", "api.example.com"} and not partial, brute
assert calls[0][0] == "-d" and str(wordlist) in calls[0], calls[0]
print("3. dnsx 爆破 ok")


# ---------- 3b. 泛解析（wildcard DNS）过滤 ----------
def fake_dnsx_wild(args, timeout=300, cancel=None):
    if "-d" in args:
        return "\n".join([
            "a.example.com [A] [169.254.254.254]",
            "b.example.com [A] [169.254.254.254]",
            "real.example.com [A] [10.0.0.5]",
        ]), False
    return "spirit-x.example.com [A] [169.254.254.254]", False


DomainCollect.dnsx_run = fake_dnsx_wild
kept, _ = DomainCollect.dnsx_brute("example.com", str(wordlist), threads=20, timeout=30)
assert set(kept) == {"real.example.com"}, kept
print("3b. 泛解析过滤 ok")

DomainCollect.dnsx_run = fake_dnsx

resolved, _ = DomainCollect.dnsx_resolve(["a.example.com", "b.example.com"], "example.com")
assert resolved == {"a.example.com": ["10.0.0.3"]}, resolved
list_arg = calls[-1][calls[-1].index("-l") + 1]
assert not Path(list_arg).exists(), "dnsx 临时列表应被清理"
print("4. dnsx 批量解析（临时列表已清理）ok")

# ---------- 5. domainCollect 聚合 ----------
DomainCollect.subfinder_domains = lambda domain, all_sources=True, timeout=150, cancel=None: {
    "example.com", "www.example.com", "mail.example.com",
}


def fake_dnsx_agg(args, timeout=300, cancel=None):
    if "-d" in args:
        return "api.example.com [A] [10.0.0.9]", False
    listing = Path(args[args.index("-l") + 1]).read_text(encoding="utf-8")
    if "spirit-" in listing:
        return "", False
    return "\n".join([
        "example.com [A] [10.0.0.1]",
        "www.example.com [A] [10.0.0.2]",
        "mail.example.com [A] [10.0.0.3]",
    ]), False


DomainCollect.dnsx_run = fake_dnsx_agg
result = DomainCollect.DomainCollectCapability().run({"domain": "example.com"})
assert result.ok, result.content
assets = Assets.list_assets("primary", limit=1000)
domains = {item.get("domain") for item in assets}
for name in ("example.com", "www.example.com", "mail.example.com",
             "api.example.com", "evil-example.com"):
    pass
assert {"example.com", "www.example.com", "mail.example.com", "api.example.com"} <= domains, domains
assert "evil-example.com" not in domains and "example.com.evil.net" not in domains, domains
crypto = {item.get("domain"): item.get("ip") for item in assets}
assert crypto.get("example.com") == "10.0.0.1", crypto
csv_text = (home / "Projects" / "primary" / "assets.csv").read_text(encoding="utf-8-sig")
assert "www.example.com" in csv_text and "api.example.com" in csv_text, csv_text
print("5. domainCollect 聚合写资产 + 总表 ok")

# ---------- 6. crtshSearch 能力单独可用 ----------
result = DomainCollect.CrtShCapability().run({"domain": "example.com"})
assert result.ok and "www.example.com" in result.content, result.content
print("6. crtshSearch 能力 ok")

# ---------- 7. 字典状态 ----------
info = DomainCollect.wordlist_info(str(wordlist))
assert info["exists"] and info["rows"] == 3, info
missing = DomainCollect.wordlist_info(str(home / "nope.txt"))
assert not missing["exists"], missing
print("7. 字典状态 ok")

render.shutdown()
print("\nALL DOMAIN COLLECT TESTS PASSED")
