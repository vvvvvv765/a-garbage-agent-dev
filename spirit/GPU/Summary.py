"""
摘要子体系（GPU 渲染体系的子体系）：预算仍超时，把最旧若干轮压成一段摘要。

同父之下直接调 ModI 发送（判据 3：父体系内部允许直接调）。
不重试——重试是 CPU 的调度策略；这里失败就当没压。
"""
from Cancel import token as cancel_token
from Config import config
from Faults import faults
from Memory import mem, USAGE
from Provider import adapter
from Turn import turn
from Usage import record as usage_record

from .Bundle import ContextBundle
from .ModI import modi

_faults = faults.for_system("Summary")

SUMMARY_INSTRUCTION = (
    "请把以上对话压缩成一段简明摘要，供后续继续对话使用。"
    "保留：用户意图与关键原话、做出的决定、文件路径与关键代码、"
    "错误与修复、待办与下一步。不要编造，不要调用工具。只输出摘要正文。"
)


class Summary:
    def summarize(self, messages):
        """把一段消息压成摘要正文；失败 / 被取消返回空串。"""
        if cancel_token.is_set():
            return ""
        instruction = {"role": "user", "content": SUMMARY_INSTRUCTION}
        bundle = ContextBundle(
            instructions=config.get("engine.system_prompt", ""),
            messages=tuple(list(messages) + [instruction]),
            meta={"purpose": "summary"},
        )

        try:
            stream = modi.request(bundle)
        except Exception as error:
            _faults.report(error, "request")
            return ""
        if stream is None:
            return ""

        ad = adapter.current()   # 这条流用同一份方言
        parts = []
        try:
            for event in stream:
                if cancel_token.is_set():
                    close = getattr(stream, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass
                    return ""
                if ad.is_text_delta(event):
                    parts.append(ad.text_delta(event))
                elif ad.is_completed(event):
                    usage = ad.usage(event)
                    if usage:
                        item = usage_record(
                            usage,
                            "summary",
                            model=str(config.get("llm.model", "")),
                            provider=str(config.get("llm.provider_id", "")),
                            pricing=config.get("llm.pricing", {}) or {},
                        )
                        item["turn"] = turn.current()
                        mem.submit(USAGE, item)
        except Exception as error:
            _faults.report(error, "consume")
            return ""
        return "".join(parts)


summary = Summary()
