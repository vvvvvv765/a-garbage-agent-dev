"""
故障转移（CPU 的子体系）：照抄 cc-switch 的「有序队列 + 优先级 + 熔断」概念。

差别：cc-switch 靠本地代理在转发层热切换；Spirit 直接把「换一家提供商」
当成一次激活 + 重建客户端（由主板注入的 switch_provider 完成）。

配置：
  llm.providers[i].in_failover_queue    谁进队列（顺序 = 提供商列表顺序，P1/P2…）
  engine.failover.enabled               总开关
  engine.failover.threshold             连续失败几次熔断
  engine.failover.cooldown              熔断多少秒（到点半开，允许再试）

判定照抄 cc-switch：
  - 熔断器由真实请求结果驱动，不由连通性测试驱动
  - 队列内按顺序找下一家；当前不在队列里 → 不转移
  - 全部熔断 / 只有一家 → 放弃，交回原来的错误
"""
import threading
import time

from Config import config
from Config import Providers
from Log import log


class Failover:
    def __init__(self):
        self.__lock = threading.RLock()
        # provider_id -> {"errors": 连续失败次数, "open_until": 熔断截止时间戳}
        self.state = {}
        self.origin = ""            # 第一次换家前的"主家"
        self.last_return_turn = None

    # ---------- 配置 ----------
    def enabled(self):
        return bool(config.get("engine.failover.enabled", False))

    def threshold(self):
        try:
            return max(1, int(config.get("engine.failover.threshold", 4) or 4))
        except (TypeError, ValueError):
            return 4

    def cooldown(self):
        try:
            return max(1.0, float(config.get("engine.failover.cooldown", 60) or 60))
        except (TypeError, ValueError):
            return 60.0

    def current(self):
        return str(config.get("llm.provider_id", "") or "")

    def queue(self):
        return [
            item["id"]
            for item in Providers.providers_of(config)
            if item.get("in_failover_queue")
        ]

    # ---------- 熔断器 ----------
    def available(self, provider_id):
        entry = self.state.get(provider_id) or {}
        return float(entry.get("open_until", 0) or 0) <= time.time()

    def record(self, provider_id, ok):
        if not provider_id:
            return
        with self.__lock:
            self.__record(provider_id, ok)

    def __record(self, provider_id, ok):
        entry = self.state.setdefault(provider_id, {"errors": 0, "open_until": 0})
        if ok:
            entry["errors"] = 0
            entry["open_until"] = 0
            return
        entry["errors"] = int(entry.get("errors", 0)) + 1
        if entry["errors"] >= self.threshold():
            entry["open_until"] = time.time() + self.cooldown()
            log.warning(
                "Failover",
                f"{provider_id} 熔断 {self.cooldown():.0f}s（连续 {entry['errors']} 次失败）",
            )

    def snapshot(self):
        now = time.time()
        with self.__lock:
            items = list(self.state.items())
        return {
            pid: {
                "errors": entry.get("errors", 0),
                "open": float(entry.get("open_until", 0) or 0) > now,
                "open_in": max(0, round(float(entry.get("open_until", 0) or 0) - now)),
            }
            for pid, entry in items
        }

    def reset(self):
        with self.__lock:
            self.state.clear()
        self.origin = ""
        self.last_return_turn = None

    # ---------- 回切主家 ----------
    def note_origin(self, provider_id):
        """第一次换家时记住主家；之后成功切回就清掉。"""
        if not self.origin and provider_id:
            self.origin = str(provider_id)

    def take_primary(self, turn_id):
        """新的一轮开始时，如果主家已恢复且当前不是主家 → 返回主家（一轮只回切一次）。"""
        if not bool(config.get("engine.failover.prefer_primary", True)):
            return None
        if not self.enabled() or not self.origin:
            return None
        if self.current() == self.origin:
            self.origin = ""
            return None
        if not self.available(self.origin):
            return None
        if self.last_return_turn == turn_id:
            return None
        self.last_return_turn = turn_id
        return self.origin

    # ---------- 选择 ----------
    def should_preempt(self):
        """当前这家是否已熔断（下次请求前就该换，而不是先白打一轮）。"""
        current = self.current()
        if not self.enabled() or not current:
            return False
        if self.available(current):
            return False
        return self.next_after(current) is not None

    def next_after(self, current):
        """按队列顺序找下一家可用的（跳过自己、跳过熔断中的）。"""
        queue = self.queue()
        if len(queue) < 2 or current not in queue:
            return None
        index = queue.index(current)
        for step in range(1, len(queue)):
            candidate = queue[(index + step) % len(queue)]
            if candidate != current and self.available(candidate):
                return candidate
        return None


failover = Failover()
