"""
资产测绘平台：FOFA / 360 Quake / 奇安信 Hunter。

设计参考全链哨兵的 asset-platforms / asset-tool：
  - 一个平台一个工具，不共用查询语法；
  - Key 只在宿主进程使用，不进模型、不进 bash；
  - 结果归一化成项目资产库，原始响应落盘；
  - 只有启用 + 配了 Key 的平台才出现在模型工具列表。
"""
import base64
import json
import time
import urllib.parse
import urllib.request

from Config import config

from .Assets import add_assets, project_dir
from .Output import CapabilityResult
from .Spec import CapabilitySpec

PLATFORMS = {
    "fofa": {
        "label": "FOFA",
        "search": "https://fofa.info/api/v1/search/all",
        "info": "https://fofa.info/api/v1/info/my",
        "syntax": 'ip="1.1.1.1"、domain="example.com"、title="后台"、body="login"、port="8080"',
        "doc": "https://fofa.info/api",
    },
    "quake": {
        "label": "360 Quake",
        "search": "https://quake.360.net/api/v3/search/quake_service",
        "info": "https://quake.360.net/api/v3/user/info",
        "syntax": 'ip:"1.1.1.1"、domain:"example.com"、title:"后台"、port:8080、service:"http"',
        "doc": "https://quake.360.net/quake/#/help",
    },
    "hunter": {
        "label": "奇安信 Hunter",
        "search": "https://hunter.qianxin.com/openApi/search",
        "info": "https://hunter.qianxin.com/openApi/userInfo",
        "syntax": 'ip="1.1.1.1"、domain="example.com"、web.title="后台"、port="8080"',
        "doc": "https://hunter.qianxin.com/home/help",
    },
}

REQUEST_TIMEOUT = 25
DEFAULT_SIZE = 20
MAX_SIZE = 100


def _setting(platform, name, default=""):
    return config.get(f"assets.platforms.{platform}.{name}", default)


def platform_state(platform):
    meta = PLATFORMS.get(platform)
    if meta is None:
        return {}
    key = str(_setting(platform, "key", "") or "").strip()
    return {
        "id": platform,
        "label": meta["label"],
        "enabled": bool(_setting(platform, "enabled", False)),
        "configured": bool(key),
        "base_url": str(_setting(platform, "base_url", "") or ""),
        "syntax": meta["syntax"],
        "doc": meta["doc"],
        "status": dict(config.get(f"assets.platforms.{platform}.status", {}) or {}),
    }


def platforms():
    return [platform_state(name) for name in PLATFORMS]


def configured(platform):
    state = platform_state(platform)
    return bool(state.get("enabled") and state.get("configured"))


def save_platform(platform, enabled=None, key=None, base_url=None):
    meta = PLATFORMS.get(platform)
    if meta is None:
        raise ValueError(f"未知平台：{platform}")
    if enabled is not None:
        config.set(f"assets.platforms.{platform}.enabled", bool(enabled))
    if key is not None and str(key).strip():
        config.set(f"assets.platforms.{platform}.key", str(key).strip())
    if base_url is not None:
        config.set(f"assets.platforms.{platform}.base_url", str(base_url).strip())
    config.save()
    return platform_state(platform)


def _endpoint(platform, default):
    base = str(_setting(platform, "base_url", "") or "").strip().rstrip("/")
    if not base:
        return default
    # 自定义地址是前缀：把官方路径接在后面
    path = urllib.parse.urlsplit(default).path
    return base + path


def _request(url, data=None, headers=None, timeout=REQUEST_TIMEOUT):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _clip(value, limit=400):
    text = str(value or "").replace("\r\n", "\n").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _fofa(query, page, size):
    key = str(_setting("fofa", "key", "")).strip()
    fields = "host,ip,port,domain,title,server,protocol,os,org,country,province,city,lastupdatetime,banner"
    params = urllib.parse.urlencode({
        "key": key,
        "qbase64": base64.b64encode(query.encode("utf-8")).decode("ascii"),
        "page": page, "size": size, "fields": fields,
    })
    data = _request(_endpoint("fofa", PLATFORMS["fofa"]["search"]) + "?" + params)
    if data.get("error"):
        raise RuntimeError(f"FOFA：{data.get('errmsg') or '查询失败'}")
    records = []
    for row in data.get("results") or []:
        if isinstance(row, dict):
            records.append(row)
        elif isinstance(row, list):
            # 未指定 fields 时 FOFA 返回数组：host,ip,port,...
            if len(row) >= 4:
                records.append({
                    "host": row[0], "ip": row[1], "port": row[2],
                    "domain": row[3], "title": row[4] if len(row) > 4 else "",
                    "server": row[5] if len(row) > 5 else "",
                })
    return records, int(data.get("total") or len(records)), data


def _quake(query, page, size):
    key = str(_setting("quake", "key", "")).strip()
    body = json.dumps({"query": query, "start": (page - 1) * size, "size": size}).encode("utf-8")
    data = _request(
        _endpoint("quake", PLATFORMS["quake"]["search"]),
        data=body,
        headers={"Content-Type": "application/json", "X-QuakeToken": key},
    )
    if data.get("code") not in (0, None):
        raise RuntimeError(f"Quake：{data.get('message') or '查询失败'}")
    records = []
    for item in data.get("data") or []:
        service = item.get("service") or {}
        http = service.get("http") or {}
        location = item.get("location") or {}
        records.append({
            "ip": item.get("ip"), "port": item.get("port"),
            "domain": item.get("domain"), "host": item.get("host"),
            "title": http.get("title") or service.get("title") or "",
            "server": http.get("server") or service.get("server") or "",
            "protocol": service.get("name") or "",
            "os": item.get("os") or "", "org": item.get("org") or "",
            "country": location.get("country"), "province": location.get("province"),
            "city": location.get("city"), "banner": _clip(service.get("raw") or http.get("body")),
            "url": http.get("url") or "",
        })
    total = int((data.get("meta") or {}).get("total") or len(records))
    return records, total, data


def _hunter(query, page, size):
    key = str(_setting("hunter", "key", "")).strip()
    encoded = base64.urlsafe_b64encode(query.encode("utf-8")).decode("ascii").rstrip("=")
    # Hunter 只接受 1/10/20/50/100；取最近的合法值
    size = min((10, 20, 50, 100), key=lambda value: abs(value - size))
    params = urllib.parse.urlencode({
        "api-key": key, "search": encoded, "page": page, "page_size": size,
    })
    data = _request(_endpoint("hunter", PLATFORMS["hunter"]["search"]) + "?" + params)
    if data.get("code") not in (200, None):
        raise RuntimeError(f"Hunter：{data.get('message') or '查询失败'}")
    payload = data.get("data") or {}
    records = []
    for item in payload.get("arr") or []:
        records.append({
            "ip": item.get("ip"), "port": item.get("port"),
            "domain": item.get("domain"), "url": item.get("url"),
            "title": item.get("web_title") or item.get("title") or "",
            "server": item.get("component") or "",
            "protocol": item.get("protocol") or "",
            "os": item.get("os_name") or "", "org": item.get("company") or "",
            "country": item.get("country"), "province": item.get("province"),
            "city": item.get("city"), "banner": _clip(item.get("header") or item.get("banner")),
        })
    total = int(payload.get("total") or len(records))
    return records, total, data


_SEARCHERS = {"fofa": _fofa, "quake": _quake, "hunter": _hunter}


def search(platform, query, page=1, size=DEFAULT_SIZE):
    searcher = _SEARCHERS.get(platform)
    if searcher is None:
        raise ValueError(f"未知平台：{platform}")
    page = max(1, int(page))
    size = max(1, min(MAX_SIZE, int(size)))
    started = time.monotonic()
    records, total, raw = searcher(query, page, size)
    latency = round((time.monotonic() - started) * 1000)
    return {
        "platform": platform, "query": query, "page": page, "size": size,
        "total": total, "records": records, "raw": raw, "latency": latency,
    }


def probe(platform):
    """用账号信息接口确认 Key 是否有效（不消耗搜索额度）。"""
    meta = PLATFORMS.get(platform)
    if meta is None:
        raise ValueError(f"未知平台：{platform}")
    key = str(_setting(platform, "key", "")).strip()
    if not key:
        raise RuntimeError(f"{meta['label']} 还没有配置 API Key")
    try:
        if platform == "fofa":
            data = _request(f"{meta['info']}?key={urllib.parse.quote(key)}")
            if data.get("error"):
                raise RuntimeError(str(data.get("errmsg") or "Key 无效"))
            quota = f"{data.get('remain_api_query', '?')} 次"
        elif platform == "quake":
            data = _request(meta["info"], headers={"X-QuakeToken": key})
            if data.get("code") not in (0, None):
                raise RuntimeError(str(data.get("message") or "Key 无效"))
            quota = str((data.get("data") or {}).get("remain_free_api", "") or "")
        else:
            data = _request(f"{meta['info']}?api-key={urllib.parse.quote(key)}")
            if data.get("code") not in (200, None):
                raise RuntimeError(str(data.get("message") or "Key 无效"))
            quota = str((data.get("data") or {}).get("rest_quota", "") or "")
        state = {"at": time.time(), "ok": True, "quota": quota, "error": ""}
    except Exception as error:
        state = {"at": time.time(), "ok": False, "error": str(error)[:300], "quota": ""}
    config.set(f"assets.platforms.{platform}.status", state)
    config.save()
    return state


class AssetSearchCapability:
    platform = ""

    def __init__(self):
        meta = PLATFORMS[self.platform]
        self.name = f"{self.platform}Search"
        self.description = (
            f"查询 {meta['label']} 的互联网资产测绘数据。"
            f"使用 {meta['label']} 自己的语法：{meta['syntax']}。"
            "结果会自动写入当前项目的资产库；没有记录只代表平台没测绘到，不代表目标不存在。"
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": f"{meta['label']} 查询语法"},
                "page": {"type": "integer", "description": "页码，从 1 开始"},
                "size": {"type": "integer", "description": "每页条数，默认 20，最大 100"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def spec(self):
        return CapabilitySpec(
            self.name, self.description, self.parameters,
            side_effect="external", trust="untrusted", timeout=90,
        )

    def available(self):
        return configured(self.platform)

    def run(self, arguments):
        if not self.available():
            return CapabilityResult(
                f"{PLATFORMS[self.platform]['label']} 未启用或没有配置 API Key。",
                {"source": "asset-platform"}, ok=False,
            )
        query = str(arguments.get("query") or "").strip()
        if not query:
            return CapabilityResult(
                "query 不能为空。语法：" + PLATFORMS[self.platform]["syntax"],
                {"source": "asset-platform"}, ok=False,
            )
        page = int(arguments.get("page") or 1)
        size = int(arguments.get("size") or DEFAULT_SIZE)
        try:
            result = search(self.platform, query, page, size)
        except Exception as error:
            config.set(f"assets.platforms.{self.platform}.status", {
                "at": time.time(), "ok": False, "error": str(error)[:300],
            })
            return CapabilityResult(
                f"{PLATFORMS[self.platform]['label']} 查询失败：{error}",
                {"source": "asset-platform"}, ok=False,
            )
        session_id = ""
        from .Executions import executions
        execution = executions.current()
        if execution is not None:
            session_id = execution.session_id
        added, total = add_assets(
            session_id, result["records"], source=self.platform,
            query=query, raw=result["raw"],
        )
        lines = [
            f"{PLATFORMS[self.platform]['label']} 查询「{query}」第 {page} 页："
            f"命中 {result['total']}，本页 {len(result['records'])}，新增 {added}，"
            f"项目共 {total} 条，耗时 {result['latency']}ms。"
        ]
        for index, item in enumerate(result["records"][:12], 1):
            where = item.get("host") or item.get("ip") or item.get("domain") or item.get("url") or "?"
            port = f":{item['port']}" if item.get("port") else ""
            title = item.get("title") or item.get("server") or ""
            lines.append(f"{index}. {where}{port} {title}")
        if len(result["records"]) > 12:
            lines.append(f"…还有 {len(result['records']) - 12} 条，完整结果在项目资产库。")
        if not result["records"]:
            lines.append("该平台没有返回记录：不代表目标不存在，换语法或换平台再试。")
        if result["total"] > page * result["size"]:
            lines.append(f"还有更多：用 page={page + 1} 取下一页。")
        lines.append(f"项目总表：{project_dir(session_id) / 'assets.csv'}")
        return CapabilityResult(
            "\n".join(lines),
            {"source": f"{self.platform}（测绘平台）", "platform": self.platform},
        )


class FofaSearchCapability(AssetSearchCapability):
    platform = "fofa"


class QuakeSearchCapability(AssetSearchCapability):
    platform = "quake"


class HunterSearchCapability(AssetSearchCapability):
    platform = "hunter"
