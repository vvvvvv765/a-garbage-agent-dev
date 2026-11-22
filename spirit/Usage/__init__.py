"""
用量账本（中立工具）：真实 token 的规范化 / 计价 / 汇总。

不做体系间的事：
  - 写数据表由生产者自己做（ModO 写对话用量，Summary 写摘要用量）
  - 这里只接收 usage dict / 数据表记录，算成本、汇总

usage 形状（provider 方言统一成这个）：
  {"input": int, "output": int, "total": int, "cached": int, "reasoning": int}
"""


def estimate_tokens(text):
    """粗估 token：CJK 按 1 字 1 token，其余按 4 字符 1 token。"""
    value = str(text or "")
    if not value:
        return 0
    cjk = sum(1 for char in value if ord(char) > 0x2E80)
    other = len(value) - cjk
    return cjk + max(0, other // 4)


def normalize(usage):
    """把 adapter 给的用量整理成固定字段；缺的补 0。"""
    usage = usage or {}

    def number(name):
        try:
            return max(0, int(usage.get(name, 0) or 0))
        except (TypeError, ValueError):
            return 0

    input_tokens = number("input")
    output_tokens = number("output")
    total = number("total") or (input_tokens + output_tokens)
    return {
        "input": input_tokens,
        "output": output_tokens,
        "total": total,
        "cached": min(number("cached"), input_tokens),
        "reasoning": number("reasoning"),
    }


def cost(usage, pricing):
    """按“每百万 token”的价格算钱；没配价格的返回 priced=False。"""
    usage = normalize(usage)
    pricing = pricing or {}
    try:
        price_in = float(pricing.get("input", 0) or 0)
        price_out = float(pricing.get("output", 0) or 0)
        price_cached = float(pricing.get("cached_input", price_in) or 0)
    except (TypeError, ValueError):
        price_in = price_out = price_cached = 0.0

    cached = usage["cached"]
    uncached = max(0, usage["input"] - cached)
    amount = (
        uncached * price_in
        + cached * price_cached
        + usage["output"] * price_out
    ) / 1_000_000.0

    priced = any(price > 0 for price in (price_in, price_out, price_cached))
    return round(amount, 6), priced, str(pricing.get("currency", "CNY") or "CNY")


def record(usage, purpose, model="", provider="", pricing=None):
    """生产者写数据表前用这个生成一条 usage 记录。"""
    usage = normalize(usage)
    amount, priced, currency = cost(usage, pricing or {})
    return {
        **usage,
        "purpose": purpose,
        "model": model,
        "provider": provider,
        "cost": amount,
        "priced": priced,
        "currency": currency,
    }


def _aggregate(items):
    totals = {
        "requests": 0,
        "input": 0,
        "output": 0,
        "cached": 0,
        "reasoning": 0,
        "total": 0,
        "cost": 0.0,
        "priced": False,
        "currency": "CNY",
        "costs": {},
    }
    costs = {}
    for item in items:
        totals["requests"] += 1
        for key in ("input", "output", "cached", "reasoning", "total"):
            totals[key] += int(item.get(key, 0) or 0)
        if item.get("priced"):
            totals["priced"] = True
            currency = str(item.get("currency") or "CNY")
            costs[currency] = costs.get(currency, 0.0) + float(item.get("cost", 0) or 0)
        elif item.get("currency") and not costs:
            totals["currency"] = item["currency"]
    if costs:
        totals["costs"] = {key: round(value, 6) for key, value in costs.items()}
        totals["currency"] = next(iter(costs))
        totals["cost"] = totals["costs"][totals["currency"]]
        totals["mixed"] = len(costs) > 1
    return totals


def report(records, window=128000, budgets=None, last_user=None):
    """从数据表记录算：整个会话 / 当前一轮的用量 + 最后一次请求。

    records 可以只给 usage 记录（省掉全表扫描）；这时要显式传 last_user
    （最后一条 user 的 seq），否则轮次边界会算成 0。
    """
    entries = [
        record.payload for record in records
        if record.address == "usage" and isinstance(record.payload, dict)
    ]
    if last_user is None:
        last_user = max(
            (record.seq for record in records if record.address == "user"),
            default=0,
        )
    turn_entries = [
        record.payload for record in records
        if record.address == "usage"
        and record.seq > last_user
        and isinstance(record.payload, dict)
    ]

    session = _aggregate(entries)
    turn = _aggregate(turn_entries)
    # 上下文占比看“最后一次对话请求”，别被摘要请求盖掉
    last = next(
        (item for item in reversed(entries) if item.get("purpose") == "chat"),
        entries[-1] if entries else None,
    )
    return {
        "session": session,
        "turn": turn,
        "last": last,
        "window": int(window or 0),
        "budgets": dict(budgets or {}),
    }
