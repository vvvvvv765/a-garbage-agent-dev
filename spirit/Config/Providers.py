"""
模型提供商的配置管理（配置体系的子模块）。

结构：
  llm.providers = [{id, name, kind, base_url, api_key, api_key_env, models: [...]}]
  llm.provider_id / model / base_url / api_key / api_key_env  = 当前生效的那个

旧配置没有 providers 时，用顶层字段合成一个，不迁移也能用。
"""
import os
import re

from Log import log
import time
from urllib.parse import urlparse

# openai 1.x 用 httpx，当前环境用 httpx2；两个 API 兼容，有一个就能探测
try:
    import httpx as _http
except ImportError:
    import httpx2 as _http

# 接口类型：openai = Responses；openai-chat = Chat Completions；anthropic = Messages
KINDS = {"openai", "openai-chat", "anthropic"}

# 认证方式（只对 anthropic 有意义）：
#   key   → 请求头 x-api-key        （cc-switch 的 ANTHROPIC_API_KEY）
#   token → 请求头 Authorization: Bearer（cc-switch 的 ANTHROPIC_AUTH_TOKEN）
AUTHS = {"key", "token"}


def _int_or(value, default=0):
    """配置里的数值字段：接受字符串数字（"64000"），坏值回默认。

    Config 加载期已经按 DEFAULTS 的形状归一过一遍；这里是第二道——
    providers 列表里的每项不在归一范围内（手改 / 旧版本可能写坏）。
    """
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

# 供应商分类（照抄 cc-switch）：决定表单显隐、列表徽章，不影响请求
CATEGORIES = ("official", "cn_official", "aggregator", "third_party",
              "cloud_provider", "custom")

CATEGORY_LABELS = {
    "official": "官方",
    "cn_official": "国内官方",
    "aggregator": "聚合平台",
    "third_party": "第三方",
    "cloud_provider": "云服务商",
    "custom": "自定义",
}

# 连通性测试 / 端点测速的超时（秒）——照抄 cc-switch 的 8 秒
CHECK_TIMEOUT = 8.0
SPEED_TIMEOUT = 8.0

# OpenCode Go 网关的要求（opencode.ai/v2/docs/console/go）：
#   - 客户端要报自己的 User-Agent（不能是 SDK / HTTP 库的默认名，否则 403）
#   - 每个会话要带稳定的 x-opencode-session（不带 → 400 MissingSessionID）
# 照抄 cc-switch 4.0 的 fallback（src-tauri/src/proxy/forwarder/opencode.rs）。
VERSION = "0.1.0"


def is_opencode(base_url):
    host = (urlparse(str(base_url or "")).hostname or "").lower()
    return host == "opencode.ai" or host.endswith(".opencode.ai")


def opencode_headers(session=None):
    headers = {"User-Agent": f"Spirit/{VERSION}"}
    if session:
        headers["x-opencode-session"] = str(session)
    return headers


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "provider"


def _kind(value, fallback="openai"):
    kind = str(value or fallback or "openai").strip().lower()
    return kind if kind in KINDS else fallback


def _auth(value, fallback="token"):
    auth = str(value or fallback or "token").strip().lower()
    return auth if auth in AUTHS else fallback


def _category(value, fallback="custom"):
    category = str(value or fallback or "custom").strip().lower()
    if category in ("omo", "omo-slim"):      # cc-switch 的 opencode 专用分类
        category = "third_party"
    return category if category in CATEGORIES else fallback


def _urls(value):
    """端点候选：字符串（一行一个）或列表 → 去空、去重、按顺序。"""
    if isinstance(value, str):
        value = re.split(r"[\r\n,]+", value)
    urls = []
    for item in value or []:
        url = str(item or "").strip().rstrip("/")
        if not url:
            continue
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError(f"端点需要以 http:// 或 https:// 开头：{url}")
        if url not in urls:
            urls.append(url)
    return urls


def normalize_base(kind, base_url):
    """整理 Base URL。

    anthropic 的 SDK 会自己在 base 后面拼 /v1/messages —— 所以 base 不能带 /v1，
    否则会变成 /v1/v1/messages（cc-switch 写 ANTHROPIC_BASE_URL 时也是这个口径）。
    """
    base = str(base_url or "").strip().rstrip("/")
    if kind == "anthropic" and base.endswith("/v1"):
        base = base[:-3].rstrip("/")
    return base


def providers_of(config):
    items = config.get("llm.providers")
    if isinstance(items, list) and items:
        return [dict(item) for item in items if isinstance(item, dict) and item.get("id")]
    return [_legacy(config)]


def _legacy(config):
    base = str(config.get("llm.base_url") or "https://api.deepseek.com")
    return {
        "id": str(config.get("llm.provider_id") or "deepseek"),
        "name": "DeepSeek",
        "kind": _kind(config.get("llm.provider")),
        "auth": _auth(config.get("llm.auth")),
        "category": "cn_official",
        "base_url": base,
        "endpoints": [base],
        "api_key": str(config.get("llm.api_key") or ""),
        "api_key_env": str(config.get("llm.api_key_env") or "DEEPSEEK_API_KEY"),
        "api_key_url": "",
        "models": [str(config.get("llm.model") or "deepseek-Flash")],
        "pricing": dict(config.get("llm.pricing") or {}),
        "context_window": _int_or(config.get("llm.context_window"), 128000) or 128000,
        "max_tokens": _int_or(config.get("llm.max_tokens"), 8192) or 8192,
        "website": "",
        "notes": "",
        "icon": "",
        "icon_color": "",
    }


def active_id(config, items=None):
    items = items or providers_of(config)
    pid = str(config.get("llm.provider_id") or "")
    ids = [item["id"] for item in items]
    return pid if pid in ids else (ids[0] if ids else "")


def current_kind(config):
    """当前生效提供商的接口类型；顶层字段缺失 / 过期时以 providers 为准。"""
    items = providers_of(config)
    active = active_id(config, items)
    item = next((entry for entry in items if entry["id"] == active), None)
    return _kind(item.get("kind") if item else config.get("llm.provider"))


def _public(item, active):
    key = str(item.get("api_key") or "")
    env_name = str(item.get("api_key_env") or "")
    from_env = bool(env_name and os.environ.get(env_name))
    return {
        "id": item["id"],
        "name": item.get("name") or item["id"],
        "kind": _kind(item.get("kind")),
        "auth": _auth(item.get("auth")),
        "base_url": item.get("base_url") or "",
        # 老配置没有 endpoints 时，至少把当前 Base URL 当唯一候选
        "endpoints": list(item.get("endpoints") or (
            [item.get("base_url")] if item.get("base_url") else []
        )),
        "models": list(item.get("models") or []),
        "pricing": dict(item.get("pricing") or {}),
        "context_window": _int_or(item.get("context_window"), 0),
        "max_tokens": _int_or(item.get("max_tokens"), 0),
        "website": item.get("website") or "",
        "notes": item.get("notes") or "",
        "category": _category(item.get("category")),
        "category_label": CATEGORY_LABELS[_category(item.get("category"))],
        "icon": item.get("icon") or "",
        "icon_color": item.get("icon_color") or "",
        "api_key_url": item.get("api_key_url") or "",
        "in_failover_queue": bool(item.get("in_failover_queue")),
        "has_key": bool(key or from_env),
        "key_hint": key[-4:] if key else "",
        "from_env": bool(not key and from_env),
        "active": item["id"] == active,
    }


def list_public(config):
    items = providers_of(config)
    active = active_id(config, items)
    return {
        "active": active,
        "model": str(config.get("llm.model") or ""),
        "providers": [_public(item, active) for item in items],
    }


def _sync_active(config, item):
    """把提供商字段同步成顶层“当前生效”配置。"""
    config.set("llm.provider_id", item["id"])
    config.set("llm.provider", item.get("kind") or "openai")
    config.set("llm.auth", _auth(item.get("auth")))
    config.set("llm.base_url", item.get("base_url") or "")
    config.set("llm.api_key", item.get("api_key") or "")
    config.set("llm.api_key_env", item.get("api_key_env") or "")
    config.set("llm.pricing", dict(item.get("pricing") or {}))


def _models(value):
    if isinstance(value, str):
        value = value.split(",")
    models = [str(item).strip() for item in (value or []) if str(item).strip()]
    return models


def validate(data):
    """只校验不写入：导入时先整批过一遍，避免写一半炸一半。"""
    name = str((data or {}).get("name") or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    kind = _kind((data or {}).get("kind"))
    base = normalize_base(kind, (data or {}).get("base_url"))
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("Base URL 需要以 http:// 或 https:// 开头")
    if not _models((data or {}).get("models")):
        raise ValueError("至少填一个模型")
    pricing = (data or {}).get("pricing") or {}
    if not isinstance(pricing, dict):
        raise ValueError("价格需要是数字（元 / 百万 token）")
    for key in ("input", "output", "cached_input"):
        value = pricing.get(key)
        if value in (None, ""):
            continue
        try:
            float(value)
        except (TypeError, ValueError):
            raise ValueError("价格需要是数字（元 / 百万 token）")
    if "endpoints" in (data or {}):
        _urls((data or {}).get("endpoints"))
    for key, low, high in (("context_window", 1000, 10_000_000),
                           ("max_tokens", 256, 1_000_000)):
        value = (data or {}).get(key)
        if value in (None, ""):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} 需要整数")
        if number < low or number > high:
            raise ValueError(f"{key} 需要在 {low}–{high} 之间")
    return True


def upsert(config, data):
    with config.mutation():
        return _upsert(config, data)


def _upsert(config, data):
    """新增 / 编辑一个提供商。api_key 为空表示“不改”，clear_key 才清空。"""
    items = providers_of(config)
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("名称不能为空")

    raw_id = str(data.get("id") or "").strip()
    pid = raw_id or _slug(name)
    ids = {item["id"] for item in items}
    if not raw_id:
        # 新建时保证 id 唯一（同名 slug 不能覆盖已有提供商）
        base, index = pid, 2
        while pid in ids:
            pid = f"{base}-{index}"
            index += 1

    item = next((entry for entry in items if entry["id"] == pid), None)
    if item is None:
        item = {
            "id": pid,
            "name": name,
            "kind": "openai",
            "auth": "token",
            "category": "custom",
            "website": "",
            "notes": "",
            "icon": "",
            "icon_color": "",
            "base_url": "",
            "endpoints": [],
            "api_key": "",
            "api_key_env": "",
            "api_key_url": "",
            "models": [],
            "pricing": {"input": 0, "output": 0, "currency": "CNY"},
        }
        items.append(item)

    kind = _kind(data.get("kind"), item.get("kind") or "openai")
    base_url = normalize_base(kind, data.get("base_url"))
    if not base_url.lower().startswith(("http://", "https://")):
        raise ValueError("Base URL 需要以 http:// 或 https:// 开头")
    models = _models(data.get("models"))
    if not models:
        raise ValueError("至少填一个模型")

    item["name"] = name
    item["kind"] = kind
    item["auth"] = _auth(data.get("auth"), item.get("auth") or "token")
    item["category"] = _category(data.get("category"), item.get("category") or "custom")
    item["base_url"] = base_url
    item["models"] = models
    if "website" in data:
        item["website"] = str(data.get("website") or "").strip()
    for field in ("notes", "icon", "icon_color", "api_key_url"):
        if field in data:
            item[field] = str(data.get(field) or "").strip()
    if "in_failover_queue" in data:
        item["in_failover_queue"] = bool(data.get("in_failover_queue"))
    for key, low, high in (("context_window", 1000, 10_000_000),
                           ("max_tokens", 256, 1_000_000)):
        if key in data:
            raw = data.get(key)
            if raw in (None, ""):
                item.pop(key, None)
                continue
            try:
                number = int(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{key} 需要整数")
            if number < low or number > high:
                raise ValueError(f"{key} 需要在 {low}–{high} 之间")
            item[key] = number
    # 端点候选：传了就用传的（保证含当前 base_url）；没传就保证至少有一条
    if "endpoints" in data:
        endpoints = []
        for url in _urls(data.get("endpoints")):
            url = normalize_base(kind, url)
            if url not in endpoints:
                endpoints.append(url)
    else:
        endpoints = list(item.get("endpoints") or [])
    endpoints = [url for url in endpoints if url != base_url]
    item["endpoints"] = [base_url] + endpoints
    # 没传 api_key_env 就保留原来的（否则编辑价格会把环境变量兜底清掉）
    if "api_key_env" in data:
        item["api_key_env"] = str(data.get("api_key_env") or "").strip()

    pricing = data.get("pricing") or {}
    if not isinstance(pricing, dict):
        raise ValueError("价格需要是数字（元 / 百万 token）")
    try:
        price_in = max(0.0, float(pricing.get("input", 0) or 0))
        item["pricing"] = {
            "input": price_in,
            "output": max(0.0, float(pricing.get("output", 0) or 0)),
            # 缓存命中价：没填就按输入价算（和以前一致）
            "cached_input": max(0.0, float(pricing.get("cached_input", price_in) or 0)),
            "currency": str(pricing.get("currency", "CNY") or "CNY").upper(),
        }
    except (TypeError, ValueError):
        raise ValueError("价格需要是数字（元 / 百万 token）")

    if data.get("clear_key"):
        item["api_key"] = ""
    elif str(data.get("api_key") or "").strip():
        item["api_key"] = str(data["api_key"]).strip()

    config.set("llm.providers", items)
    active = active_id(config, items)
    if pid == active:
        _sync_active(config, item)
        current = str(config.get("llm.model") or "")
        if current not in item["models"]:
            config.set("llm.model", item["models"][0])
    config.save()
    return _public(item, active)


def active_value(config, key, default):
    """取"当前生效"的数值型属性：优先当前提供商自己的，其次全局 llm.*。

    上下文窗口 / 最大输出跟着提供商走；provider 没写就用全局设置（设置页）。
    """
    items = providers_of(config)
    item = next(
        (entry for entry in items if entry["id"] == active_id(config, items)),
        None,
    )
    if item is not None and item.get(key):
        try:
            return int(item[key])
        except (TypeError, ValueError):
            pass
    try:
        return int(config.get(f"llm.{key}", default) or default)
    except (TypeError, ValueError):
        return default


def sync_active(config):
    with config.mutation():
        return _sync_active_provider(config)


def _sync_active_provider(config):
    """启动对账：providers 列表存在时，把顶层 llm.* 同步成当前提供商。

    以前只在 upsert / activate 里同步；手工替换 config.json、只导入 providers、
    从导出文件恢复时会留下"kind 取 A 家、base_url / Key 取 B 家"的错配。
    """
    items = providers_of(config)
    if not config.get("llm.providers"):
        return None   # 旧扁平配置：以顶层为准，不做反向覆盖
    item = next(
        (entry for entry in items if entry["id"] == active_id(config, items)),
        None,
    )
    if item is None:
        return None
    _sync_active(config, item)
    return item


def activate(config, provider_id, model=None):
    with config.mutation():
        return _activate(config, provider_id, model)


def _activate(config, provider_id, model=None):
    items = providers_of(config)
    item = next((entry for entry in items if entry["id"] == provider_id), None)
    if item is None:
        raise ValueError(f"没有这个提供商：{provider_id}")

    models = list(item.get("models") or [])
    model = str(model or "").strip() or (models[0] if models else "")
    if models and model not in models:
        log.warning("Providers", f"{provider_id} 没有模型 {model}，回落到 {models[0]}")
        model = models[0]

    _sync_active(config, item)
    config.set("llm.model", model)
    config.save()
    return model


def remove(config, provider_id):
    with config.mutation():
        return _remove(config, provider_id)


def _remove(config, provider_id):
    items = providers_of(config)
    if len(items) <= 1:
        raise ValueError("至少要保留一个提供商")
    if provider_id == active_id(config, items):
        raise ValueError("当前正在使用这个提供商，先切换到别的再删")
    items = [item for item in items if item["id"] != provider_id]
    config.set("llm.providers", items)
    config.save()
    return list_public(config)


def duplicate(config, provider_id):
    with config.mutation():
        return _duplicate(config, provider_id)


def _duplicate(config, provider_id):
    """复制一个提供商（含 Key），名称加 copy，排在原项后面。"""
    items = providers_of(config)
    source = next((item for item in items if item["id"] == provider_id), None)
    if source is None:
        raise ValueError(f"没有这个提供商：{provider_id}")

    copy = dict(source)
    copy["name"] = f"{source.get('name') or source['id']} copy"
    copy["models"] = list(source.get("models") or [])
    copy["endpoints"] = list(source.get("endpoints") or [])
    copy["pricing"] = dict(source.get("pricing") or {})
    ids = {item["id"] for item in items}
    base = _slug(copy["name"])
    pid, index = base, 2
    while pid in ids:
        pid = f"{base}-{index}"
        index += 1
    copy["id"] = pid

    position = next(i for i, item in enumerate(items) if item["id"] == provider_id)
    items.insert(position + 1, copy)
    config.set("llm.providers", items)
    config.save()
    return _public(copy, active_id(config, items))


def reorder(config, ordered_ids):
    with config.mutation():
        return _reorder(config, ordered_ids)


def _reorder(config, ordered_ids):
    """按给定 id 顺序重排提供商（照抄 cc-switch 的拖拽排序）。

    没出现在列表里的项保持原相对顺序，排在最后；不认识的 id 忽略。
    """
    items = providers_of(config)
    by_id = {item["id"]: item for item in items}
    ordered = []
    for pid in ordered_ids or []:
        item = by_id.pop(str(pid), None)
        if item is not None:
            ordered.append(item)
    ordered.extend(by_id.values())
    if not ordered:
        raise ValueError("提供商列表不能为空")
    config.set("llm.providers", ordered)
    config.save()
    return list_public(config)


def find(config, provider_id):
    item = next(
        (entry for entry in providers_of(config) if entry["id"] == str(provider_id)),
        None,
    )
    if item is None:
        raise ValueError(f"没有这个提供商：{provider_id}")
    return item


# ---------- 连通性测试 / 端点测速（照抄 cc-switch 的判定） ----------

def _local_host(url):
    host = (urlparse(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def check(base_url, timeout=CHECK_TIMEOUT):
    """连通性测试：只 GET 一次 base URL，**不带 Key、不碰模型**。

    照 cc-switch 的职责划分：只要拿到 HTTP 响应（200/401/403/404/429/5xx）
    就算可达；只有 DNS / 连接被拒 / TLS / 超时这类网络错误才算不可达。
    鉴权与模型是否存在由“获取模型”/真实调用验证，不在这一步下结论。
    """
    url = str(base_url or "").strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("Base URL 需要以 http:// 或 https:// 开头")

    probe_headers = {"Accept": "*/*", "Accept-Encoding": "identity"}
    if is_opencode(url):
        probe_headers.update(opencode_headers("spirit-check"))
    started = time.monotonic()
    try:
        with _http.Client(
            timeout=timeout,
            trust_env=not _local_host(url),
            follow_redirects=False,   # 3xx 本身就是“可达”，别跟跳转绕进循环
        ) as client:
            response = client.get(url, headers=probe_headers)
    except Exception as error:
        elapsed = int((time.monotonic() - started) * 1000)
        return {
            "reachable": False,
            "status": 0,
            "latency_ms": elapsed,
            "level": "failed",
            "error": f"{type(error).__name__}: {error}",
        }

    elapsed = int((time.monotonic() - started) * 1000)
    level = "operational" if elapsed <= 6000 else "degraded"
    return {
        "reachable": True,
        "status": int(response.status_code),
        "redirects": 0,
        "latency_ms": elapsed,
        "level": level,
        "authenticated": False,
        "error": "",
    }


def speed_test(urls, timeout=SPEED_TIMEOUT):
    """端点测速：每个地址先热身一次（结果丢掉），再计时一次。

    照抄 cc-switch：只要拿到 HTTP 响应就有延迟（不看状态码），
    只有网络错误 / 超时算失败；超时钳到 2~30 秒之间。
    """
    timeout = max(2.0, min(30.0, float(timeout or SPEED_TIMEOUT)))
    cleaned = _urls(urls)
    if not cleaned:
        raise ValueError("至少给一个端点")

    results = []
    for url in cleaned:
        probe_headers = {"Accept": "*/*", "Accept-Encoding": "identity"}
        if is_opencode(url):
            probe_headers.update(opencode_headers("spirit-speedtest"))
        started = time.monotonic()
        try:
            with _http.Client(
                timeout=timeout,
                trust_env=not _local_host(url),
                follow_redirects=True,   # 同 cc-switch：测的是最终端点
            ) as client:
                # 热身：连接握手 / DNS / TLS 预热，结果丢掉
                try:
                    client.get(url, headers=probe_headers)
                except Exception:
                    pass
                began = time.monotonic()
                response = client.get(url, headers=probe_headers)
                elapsed = int((time.monotonic() - began) * 1000)
            results.append({
                "url": url,
                "ok": True,
                "status": int(response.status_code),
                "latency_ms": elapsed,
                "error": "",
            })
        except Exception as error:
            elapsed = int((time.monotonic() - started) * 1000)
            results.append({
                "url": url,
                "ok": False,
                "status": 0,
                "latency_ms": elapsed,
                "error": f"{type(error).__name__}: {error}",
            })

    results.sort(key=lambda item: (not item["ok"], item["latency_ms"]))
    best = next((item["url"] for item in results if item["ok"]), "")
    return {"results": results, "best": best}


def _extract_models(data):
    if isinstance(data, dict):
        raw = data.get("data")
        if raw is None:
            raw = data.get("models")
        if raw is None:
            raw = data.get("items")
    else:
        raw = data
    if not isinstance(raw, list):
        return []
    models = []
    for item in raw:
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = item.get("id") or item.get("slug") or item.get("name") or item.get("model")
        else:
            name = None
        if isinstance(name, str) and name.startswith("models/"):
            name = name[len("models/"):]
        if name:
            models.append(str(name))
    # 保留厂商返回顺序（去重即可，不要排序）
    return list(dict.fromkeys(models))


def probe_models(base_url, api_key, kind="openai", auth="token", timeout=12.0):
    """向端点要模型列表（/models 或 /v1/models）。

    只读探测：不写配置、不打印 Key。失败抛 ValueError（给前端显示）。
    anthropic 走 x-api-key / Bearer 两套认证，并带 anthropic-version。
    """
    kind = _kind(kind)
    auth = _auth(auth)
    base = normalize_base(kind, base_url)
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("Base URL 需要以 http:// 或 https:// 开头")
    if not str(api_key or "").strip():
        raise ValueError("先填 API Key（编辑已有提供商可以留空）")

    candidates = []
    # 以 /v{N} 结尾：版本号已在路径里，模型端点是 {base}/models
    last_segment = base.rsplit("/", 1)[-1]
    versioned = (
        last_segment.startswith("v")
        and len(last_segment) > 1
        and last_segment[1:].isdigit()
    )
    if versioned:
        candidates.append(f"{base}/models")
        if not base.endswith("/v1"):
            candidates.append(f"{base}/v1/models")
    else:
        candidates.append(f"{base}/v1/models")

    # 兼容子路径（照 cc-switch）：剥掉 /anthropic、/api/anthropic、/claudecode…
    # 再在根地址上找 /v1/models、/models
    for suffix in (
        "/api/claudecode", "/api/anthropic", "/apps/anthropic", "/api/coding",
        "/claudecode", "/anthropic", "/step_plan", "/coding", "/claude",
    ):
        if not base.endswith(suffix):
            continue
        root = base[: -len(suffix)].rstrip("/")
        if root and "://" in root:
            candidates.extend([f"{root}/v1/models", f"{root}/models"])
            if suffix == "/apps/anthropic":
                candidates.append(f"{root}/compatible-mode/v1/models")
        break

    urls = list(dict.fromkeys(candidates))
    key = str(api_key).strip()
    headers = {"Accept": "application/json", "User-Agent": "Spirit/0.1"}
    if kind == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if auth == "token":
            headers["Authorization"] = f"Bearer {key}"
        else:
            headers["x-api-key"] = key
    else:
        headers["Authorization"] = f"Bearer {key}"
    if is_opencode(base):
        headers.update(opencode_headers("spirit-model-probe"))
    host = (urlparse(base).hostname or "").lower()
    local = host in {"localhost", "127.0.0.1", "::1"}
    errors = []
    with _http.Client(
        timeout=timeout,
        trust_env=not local,   # 本地端点（Ollama 等）不要走代理
        follow_redirects=True,
    ) as client:
        for url in urls:
            try:
                response = client.get(url, headers=headers)
            except _http.TimeoutException:
                errors.append("请求超时")
                continue
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
                continue

            if response.status_code in (401, 403):
                raise ValueError("密钥无效或无权限（401/403）")
            if response.status_code in (404, 405):
                errors.append(f"{url} 不支持获取模型（{response.status_code}）")
                continue
            if response.status_code >= 400:
                errors.append(f"{url} 返回 {response.status_code}")
                continue
            try:
                data = response.json()
            except Exception:
                errors.append(f"{url} 返回的不是 JSON")
                continue
            models = _extract_models(data)
            if models:
                return models
            errors.append(f"{url} 返回里没有模型列表")

    detail = errors[-1] if errors else "没有可用的 /models 端点"
    raise ValueError(f"获取模型列表失败：{detail}")
