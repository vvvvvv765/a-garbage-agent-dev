"""
该包是 Agent 计算机的内存体系（虚拟地址 + 并发接收）
"""
from .Memory import mem, Record
from .Addresses import (
    USER, STREAM, ASSISTANT, TOOL_CALL, TOOL_OUTPUT, TOOL_STREAM, REASONING, EXCEPTION, SUMMARY,
    TODO, USAGE,
)
