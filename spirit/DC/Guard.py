"""
循环守卫子体系（CPU 的子体系）：预算硬停 + 重复调用检测。

为什么不归 GPU / 渲染：
  - 要不要“停这一轮”是调度决策，CPU 说了算
  - 渲染只负责把结果显示给人看，它没有权力停

预算读的是真实 usage（数据表 usage 地址）；重复检测看的是 CPU 手里的
tool_call 签名，不碰能力内部。
"""
import json

from Config import config
from Config import Providers
from Memory import mem, USER, USAGE
from Usage import report

# 轮询类能力允许重复（等输出 / 看进程），不算死循环
POLLING = {"processOutput", "processList"}


class Guard:
    def __init__(self):
        self.__seen = {}

    def reset(self):
        self.__seen = {}

    # ---------- 重复调用 ----------
    @staticmethod
    def __signature(name, raw):
        try:
            data = json.loads(raw) if raw else {}
            text = json.dumps(data, sort_keys=True, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            text = str(raw or "")
        return f"{name}|{text}"

    def repeated(self, name, raw_arguments):
        """这个调用是不是该拦了（达到重复上限）。"""
        try:
            limit = int(config.get("engine.repeat_limit", 3) or 0)
        except (TypeError, ValueError):
            limit = 3
        if limit <= 0 or name in POLLING:
            return False
        signature = self.__signature(name, raw_arguments)
        count = self.__seen.get(signature, 0) + 1
        self.__seen[signature] = count
        return count >= limit

    # ---------- 预算 ----------
    def budget_stop(self):
        """超预算返回一句人话；没超返回空串。"""
        limits = {
            "max_turn_tokens": _number("engine.max_turn_tokens"),
            "max_session_tokens": _number("engine.max_session_tokens"),
            "max_turn_cost": _number("engine.max_turn_cost"),
            "max_session_cost": _number("engine.max_session_cost"),
        }
        if not any(value > 0 for value in limits.values()):
            return ""

        mem.flush()
        # 只取 usage 记录 + 最后一条 user 的 seq：不复制整张表
        data = report(
            mem.view(USAGE),
            window=Providers.active_value(config, "context_window", 128000),
            budgets=limits,
            last_user=mem.last_seq(USER),
        )
        turn, session = data["turn"], data["session"]
        checks = [
            ("max_turn_tokens", turn["total"], "本轮 token"),
            ("max_session_tokens", session["total"], "会话 token"),
            ("max_turn_cost", turn["cost"], "本轮成本"),
            ("max_session_cost", session["cost"], "会话成本"),
        ]
        for key, value, label in checks:
            limit = limits[key]
            if limit > 0 and value > limit:
                if key.endswith("cost"):
                    return f"{label}预算已用完：{value:.4f} > {limit:g}"
                return f"{label}预算已用完：{value} > {limit:g}"
        return ""


def _number(path):
    try:
        return max(0.0, float(config.get(path, 0) or 0))
    except (TypeError, ValueError):
        return 0.0


guard = Guard()
