"""
该模块用于建立 Agent 客户端，是该包的主要模块（BIOS）
"""
import os

from openai import OpenAI

try:
    from anthropic import Anthropic
except ImportError:          # 只用 OpenAI 兼容家时不必装 Anthropic SDK
    Anthropic = None

from Contract import Contract
from Bus import NT, keys
from Config import Providers
from Config import config
from Faults import faults
from Log import log

_faults = faults.for_system("BIOS")

# Anthropic SDK 在构造时会自己读这两个环境变量当凭据；不隔离的话，用户机器上
# 跑 Claude Code 留下的 Key 会被悄悄发给任意提供商（还会和 x-api-key 同时发出）。
_ANTHROPIC_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _anthropic_client(key, base_url, auth, timeout=120.0):
    """按认证方式建 Anthropic 客户端。

    auth=key   → 只发 x-api-key（对应 cc-switch 的 ANTHROPIC_API_KEY）
    auth=token → Authorization: Bearer（对应 ANTHROPIC_AUTH_TOKEN）
    """
    saved = {name: os.environ.pop(name, None) for name in _ANTHROPIC_ENV}
    try:
        if auth == "token":
            return Anthropic(api_key=None, auth_token=key, base_url=base_url or None, timeout=timeout, max_retries=0)
        return Anthropic(
            api_key=None,
            auth_token=None,
            base_url=base_url or None,
            default_headers={"x-api-key": key},
            timeout=timeout,
            max_retries=0,
        )
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


class AIClient:
    def __init__(self):
        self.llm = None
        self.__client = None

    def Create(self):
        """BIOS 自检 + 产出模型句柄；产物自己进表，向 CPU 报告。"""
        # Key 优先用配置里直接写的；没有再读环境变量（兼容旧用法）
        deep_key = str(config.get("llm.api_key", "") or "").strip()
        env_name = str(config.get("llm.api_key_env", "") or "").strip()
        if not deep_key and env_name:
            deep_key = os.environ.get(env_name, "").strip()
        if not deep_key:
            where = env_name or "llm.api_key"
            _faults.report_message(f"未配置 API KEY（{where}）", "Create")
            NT.register(keys.AGENT_START, Contract(SI=False))
            return

        kind = Providers.current_kind(config)
        base_url = str(config.get("llm.base_url", "") or "")
        try:
            timeout = max(5.0, float(config.get("llm.timeout", 120) or 120))
        except (TypeError, ValueError):
            timeout = 120.0
        try:
            if kind == "anthropic":
                if Anthropic is None:
                    _faults.report_message("未安装 anthropic SDK", "Create")
                    NT.register(keys.AGENT_START, Contract(SI=False))
                    return
                ai = _anthropic_client(
                    deep_key,
                    base_url,
                    str(config.get("llm.auth", "token") or "token").lower(),
                    timeout,
                )
                self.llm = ai.messages
            else:
                ai = OpenAI(
                    api_key=deep_key,
                    base_url=base_url or "https://api.deepseek.com",
                    timeout=timeout,
                    max_retries=0,      # 重试只归 Reconnect，不让 SDK 再叠一层
                )
                self.llm = ai.chat.completions if kind == "openai-chat" else ai.responses
        except Exception as error:
            _faults.report(error, "Create")
            NT.register(keys.AGENT_START, Contract(SI=False))
            return

        # 旧客户端要关掉，不然反复切供应商会漏连接
        old_client = self.__client
        if old_client is not None:
            try:
                old_client.close()
            except Exception:
                pass
        self.__client = ai

        # 产物自己进表（不经 CPU 搬运）；切提供商 / 重启客户端时会换句柄，明确允许替换
        NT.register(keys.LLM, self.llm, replace=True)
        # 向 CPU 报告启动结果
        NT.register(keys.AGENT_START, Contract(SI=True))
        log.info("BIOS", f"Create ok ({kind})")


# 客户端实例对象，多体系共用
client = AIClient()
