"""
脱敏（中立工具）：审计 / 日志落盘前把密钥、Token 打码。

只管文本，不碰任何体系。
"""
import re

PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-***"),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{8,}\b"), "gh*_***"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "AKIA***"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"',}]+"), r"\1***"),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s\"',}]+"), r"\1***"),
    (
        re.compile(
            r"(?i)(api[_-]?key|access[_-]?token|token|secret|password|passwd)"
            r"([\"']?\s*[:=]\s*[\"']?)([^\"'\\\s,}]+)"
        ),
        r"\1\2***",
    ),
]


def redact(text, extra=()):
    """把文本里的密钥打码；extra 是额外要按原值替换的字符串（如当前 Key）。"""
    value = str(text or "")
    for secret in extra:
        secret = str(secret or "")
        if len(secret) >= 6:
            value = value.replace(secret, "***")
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    return value
