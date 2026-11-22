"""
余额查询（配置体系的子模块）：按 base_url 的 host 识别供应商，调它固定的余额接口。

来源：照抄 cc-switch 的 `balance` 模板（src-tauri/src/services/balance.rs）：
  - 识别用 host（api.deepseek.com / api.stepfun.com / api.siliconflow.cn /
    openrouter.ai / api.novita.ai），请求走各家固定的官方地址，不拼接用户 base_url；
  - 余额为 0 不代表 Key 失效（失效只看 401/403），交给前端按余额红字显示。
差别：Spirit 不执行用户自定义 JS 脚本；识别不了就明确返回「不支持」。
"""
import os
from urllib.parse import urlparse

try:
    import httpx as _http
except ImportError:                       # 与 Providers.py 同一个兼容策略
    import httpx2 as _http


def _key_of(item):
    key = str(item.get("api_key") or "").strip()
    if not key:
        env_name = str(item.get("api_key_env") or "").strip()
        if env_name:
            key = os.environ.get(env_name, "").strip()
    return key


def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value == value and value not in (float("inf"), float("-inf")) else None


def _local(host):
    return host in {"localhost", "127.0.0.1", "::1"}


def _get(url, key, timeout, headers=None, bearer=True):
    merged = {"Authorization": (f"Bearer {key}" if bearer else key),
              "Accept": "application/json"}
    merged.update(headers or {})
    host = (urlparse(url).hostname or "").lower()
    with _http.Client(
        timeout=timeout,
        trust_env=not _local(host),
        follow_redirects=True,
    ) as client:
        return client.get(url, headers=merged)


def _payload(response, source):
    if response.status_code in (401, 403):
        raise ValueError("密钥无效或无权限（401/403）")
    if response.status_code >= 400:
        raise ValueError(f"{source} 余额接口返回 {response.status_code}")
    try:
        return response.json() or {}
    except Exception as error:
        raise ValueError(f"{source} 余额接口返回的不是 JSON：{error}") from error


# ---------- 各家适配器（固定官方地址，照 cc-switch） ----------

def _deepseek(key, timeout, base=""):
    """GET https://api.deepseek.com/user/balance"""
    data = _payload(_get("https://api.deepseek.com/user/balance", key, timeout),
                    "DeepSeek")
    items = []
    for info in data.get("balance_infos") or []:
        currency = str(info.get("currency") or "CNY").upper()
        items.append({
            "label": currency,
            "total": None,
            "used": None,
            "remaining": _num(info.get("total_balance")),
            "unit": currency,
            "detail": {
                "充值余额": info.get("topped_up_balance"),
                "赠送余额": info.get("granted_balance"),
            },
        })
    if not items:
        raise ValueError("DeepSeek 余额接口没有返回钱包信息")
    # 同一账号会列出 CNY / USD 两个钱包：还有余额时不再显示空钱包
    if any(item["remaining"] is not None and item["remaining"] > 0 for item in items):
        items = [item for item in items
                 if item["remaining"] is None or item["remaining"] > 0]
    return items


def _stepfun(key, timeout, base=""):
    """GET https://api.stepfun.com/v1/accounts"""
    data = _payload(_get("https://api.stepfun.com/v1/accounts", key, timeout), "StepFun")
    return [{
        "label": "StepFun",
        "total": None,
        "used": None,
        "remaining": _num(data.get("balance")),
        "unit": "CNY",
        "detail": {
            "现金余额": data.get("total_cash_balance"),
            "代金券余额": data.get("total_voucher_balance"),
        },
    }]


def _siliconflow(key, timeout, base=""):
    """GET https://api.siliconflow.cn/v1/user/info（.com 为国际站）"""
    is_cn = "siliconflow.com" not in (urlparse(base).hostname or "")
    host = "api.siliconflow.cn" if is_cn else "api.siliconflow.com"
    data = _payload(_get(f"https://{host}/v1/user/info", key, timeout), "SiliconFlow")
    info = data.get("data") or {}
    return [{
        "label": "SiliconFlow" if is_cn else "SiliconFlow (EN)",
        "total": None,
        "used": None,
        "remaining": _num(info.get("totalBalance")),
        "unit": "CNY" if is_cn else "USD",
        "detail": {"充值余额": info.get("chargeBalance")},
    }]


def _openrouter(key, timeout, base=""):
    """GET https://openrouter.ai/api/v1/credits"""
    data = _payload(_get("https://openrouter.ai/api/v1/credits", key, timeout), "OpenRouter")
    credits = data.get("data") or data
    total = _num(credits.get("total_credits"))
    used = _num(credits.get("total_usage"))
    if total is None or used is None:
        raise ValueError("OpenRouter 余额接口缺少 total_credits / total_usage")
    return [{
        "label": "OpenRouter",
        "total": total,
        "used": used,
        "remaining": total - used,
        "unit": "USD",
        "detail": {},
    }]


def _novita(key, timeout, base=""):
    """GET https://api.novita.ai/v3/user/balance（金额单位 0.0001 USD）"""
    data = _payload(_get("https://api.novita.ai/v3/user/balance", key, timeout), "Novita AI")
    available = _num(data.get("availableBalance"))
    if available is None:
        raise ValueError("Novita AI 余额接口缺少 availableBalance")
    return [{
        "label": "Novita AI",
        "total": None,
        "used": None,
        "remaining": available / 10000.0,
        "unit": "USD",
        "detail": {"现金余额": _num(data.get("cashBalance"))},
    }]


def _zhipu(key, timeout, base=""):
    """GET {open.bigmodel.cn | api.z.ai}/api/biz/account/query-customer-account-report"""
    host = (urlparse(base).hostname or "").lower()
    is_cn = host.endswith("bigmodel.cn")
    root = "https://open.bigmodel.cn" if is_cn else "https://api.z.ai"
    response = _get(
        f"{root}/api/biz/account/query-customer-account-report",
        key, timeout, headers={"Accept-Language": "en-US,en"}, bearer=False,
    )
    data = _payload(response, "智谱")
    if data.get("success") is False:
        raise ValueError(f"智谱余额接口报错：{data.get('msg') or '未知错误'}")
    info = data.get("data") if isinstance(data.get("data"), dict) else data
    available = _num(info.get("availableBalance"))
    if available is None:
        available = _num(info.get("balance"))
    if available is None:
        raise ValueError("智谱余额接口缺少 availableBalance")
    return [{
        "label": "智谱 GLM" if is_cn else "Z.ai",
        "total": None,
        "used": None,
        "remaining": available,
        "unit": "CNY" if is_cn else "USD",
        "detail": {"冻结余额": info.get("frozenBalance")},
    }]


def _moonshot(key, timeout, base=""):
    """GET https://api.moonshot.cn/v1/users/me/balance（cc-switch 未收录，保留原有支持）"""
    host = "api.moonshot.ai" if "moonshot.ai" in (urlparse(base).hostname or "") \
        else "api.moonshot.cn"
    data = _payload(_get(f"https://{host}/v1/users/me/balance", key, timeout), "Moonshot")
    info = data.get("data") or {}
    return [{
        "label": "可用余额",
        "total": None,
        "used": None,
        "remaining": _num(info.get("available_balance")),
        "unit": "CNY",
        "detail": {
            "现金余额": info.get("cash_balance"),
            "代金券余额": info.get("voucher_balance"),
        },
    }]


# host（精确）→ (来源 id, 适配器)
ADAPTERS = (
    ({"api.deepseek.com"}, "deepseek", _deepseek),
    ({"api.stepfun.ai", "api.stepfun.com"}, "stepfun", _stepfun),
    ({"api.siliconflow.cn", "api.siliconflow.com"}, "siliconflow", _siliconflow),
    ({"openrouter.ai"}, "openrouter", _openrouter),
    ({"api.novita.ai"}, "novita", _novita),
    ({"open.bigmodel.cn", "api.z.ai"}, "zhipu", _zhipu),
    ({"api.moonshot.cn", "api.moonshot.ai"}, "moonshot", _moonshot),
)


def query(item, timeout=15.0):
    """查一个提供商的余额。返回 {ok, source, items, error, transient}。

    - 配置问题（没 Key / 地址非法 / 不支持）抛 ValueError
    - 网络问题 → ok=False + transient=True（前端可以重试、保留上次值）
    - 鉴权 / 状态码 / 解析问题 → ok=False + transient=False
    """
    base = str(item.get("base_url") or "").strip().rstrip("/")
    if not base.lower().startswith(("http://", "https://")):
        raise ValueError("Base URL 需要以 http:// 或 https:// 开头")
    key = _key_of(item)
    if not key:
        raise ValueError("这个提供商没有配置 API Key，查不了余额")

    host = (urlparse(base).hostname or "").lower()
    for hosts, source, adapter in ADAPTERS:
        if host not in hosts:
            continue
        try:
            items = adapter(key, timeout, base)
        except ValueError as error:
            message = str(error)
            transient = "余额接口返回" in message
            return {"ok": False, "source": source, "items": [],
                    "error": message, "transient": transient}
        except Exception as error:
            return {"ok": False, "source": source, "items": [],
                    "error": f"{type(error).__name__}: {error}",
                    "transient": True}
        return {"ok": True, "source": source, "items": items,
                "error": "", "transient": False}

    raise ValueError(
        "这个提供商没有内置的余额查询（支持 DeepSeek / StepFun / SiliconFlow / "
        "OpenRouter / Novita / 智谱 / Moonshot）"
    )
