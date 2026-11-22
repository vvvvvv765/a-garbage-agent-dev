"""
重连子体系（CPU 的子体系）：请求 + 消费流的失败分类、退避重试、放弃报告。

为什么归 CPU：重试是"这一轮怎么跑"的调度策略，不是哪一家的能力。
CPU 手里有 fetch（GPU）和 consume（内存）两头，串起来交给它。

只认识两个东西：
  fetch() -> stream        发一次请求
  consume(stream) -> calls 消费一条流

失败分两类：
  - 可重试：网络 / 超时 / 限流 / 5xx / 流中断
  - 不可重试：鉴权 / 无权限 / 参数错误 / 不存在
"""
import time
from dataclasses import dataclass

from Cancel import token as cancel_token

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from Log import log


@dataclass
class AttemptResult:
    ok: bool
    calls: list
    error: str | None = None


class Reconnect:
    def __init__(self, max_attempts=5, base_delay=1, max_delay=30):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.__retry = {"active": False, "attempt": 0, "limit": 0, "error": ""}

    def snapshot(self):
        """给界面看的重试状态（不阻塞、不抛异常）。"""
        return dict(self.__retry)

    def __set_retry(self, active, attempt=0, limit=0, error=""):
        self.__retry = {
            "active": bool(active), "attempt": int(attempt),
            "limit": int(limit), "error": str(error or "")[:200],
        }

    def chat(self, fetch, consume):
        """跑一次「请求 + 消费」；失败按策略重连。"""
        delay = self.base_delay
        last_error = None
        limit = self.max_attempts
        used = 0
        self.__set_retry(False)

        for attempt in range(1, self.max_attempts + 1):
            if cancel_token.is_set():
                self.__set_retry(False)
                return AttemptResult(False, [], "已取消")
            used = attempt
            try:
                stream = fetch()
                if stream is None:
                    self.__set_retry(False)
                    return AttemptResult(True, [])
                calls = consume(stream)
                self.__set_retry(False)
                return AttemptResult(True, calls)
            except Exception as error:
                last_error = error
                if not self.retryable(error):
                    self.__set_retry(False)
                    return AttemptResult(False, [], f"不可重试的错误：{self.describe(error)}")
                # 503 多是上游分组维护 / 暂时不可用：三次还不恢复就尽快把原因给用户
                if self.status_of(error) == 503:
                    limit = min(limit, 3)
                if attempt >= limit:
                    break
                self.__set_retry(True, attempt, limit, self.describe(error))
                log.warning(
                    "Reconnect",
                    f"attempt {attempt}/{limit} failed: "
                    f"{type(error).__name__}: {error}",
                )
                # 退避等待可被"停止"打断
                if cancel_token.wait(delay):
                    self.__set_retry(False)
                    return AttemptResult(False, [], "已取消")
                delay = min(delay * 2, self.max_delay)

        self.__set_retry(False)
        return AttemptResult(False, [], self.final_error(last_error, used))

    @classmethod
    def final_error(cls, error, attempts):
        status = cls.status_of(error)
        if status == 503:
            return (
                f"模型服务暂时不可用（HTTP 503），已重试 {attempts} 次；"
                "请稍后再试或切换模型"
            )
        return f"重连 {attempts} 次仍失败：{cls.describe(error)}"

    @staticmethod
    def status_of(error):
        """从异常里取 HTTP 状态码；OpenAI / Anthropic SDK 字段位置不同，都试一遍。"""
        code = getattr(error, "status_code", None)
        if code is None:
            code = getattr(getattr(error, "response", None), "status_code", None)
        try:
            return int(code) if code is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def describe(cls, error):
        """给模型 / 人看的错误摘要：类型 + HTTP 状态 + 原文 + 请求地址。

        Anthropic SDK 的异常不在 openai 的类里；不把状态码和地址带出来，
        405 / 404 这类配置错误会看起来像网络故障。
        """
        parts = [type(error).__name__]
        status = cls.status_of(error)
        if status is not None:
            parts.append(f"HTTP {status}")
        text = str(error).strip()
        if text and text not in parts:
            parts.append(text[:300])
        url = getattr(getattr(error, "request", None), "url", None)
        if url:
            parts.append(f"请求地址：{url}")
        return " · ".join(parts)

    @classmethod
    def retryable(cls, error):
        """不可重试的直接放弃；其余按可重试处理（含流中断）。"""
        if isinstance(error, (AuthenticationError, PermissionDeniedError,
                              BadRequestError, NotFoundError)):
            return False
        if isinstance(error, (APIConnectionError, APITimeoutError,
                              RateLimitError, InternalServerError)):
            return True
        # Anthropic 等其它 SDK：按状态码分类
        status = cls.status_of(error)
        if status is not None:
            return status not in (400, 401, 403, 404, 405, 422)
        return True


reconnect = Reconnect()
