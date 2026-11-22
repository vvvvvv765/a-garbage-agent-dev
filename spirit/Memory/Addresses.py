"""
虚拟地址：内存里每种数据占一个地址
"""
USER = "user"                # 用户输入
STREAM = "stream"            # 正文流式片段（瞬态：不 seq、不落盘、轮末清空）
ASSISTANT = "assistant"      # 大模型正文（整段，流结束时写一条）
TOOL_CALL = "tool_call"      # 大模型对工具的调用
TOOL_OUTPUT = "tool_output"  # 工具的执行结果
TOOL_STREAM = "tool_stream"  # 工具执行中的实时输出片段（瞬态，不落盘）
REASONING = "reasoning"      # 思考（目前只存不送）
EXCEPTION = "exception"      # 异常（只存、给人看，不送大模型）
SUMMARY = "summary"          # 摘要压缩（text + 遮蔽范围 end_seq）
TODO = "todo"                # 待办清单（最新一条生效；跟着会话落盘）
USAGE = "usage"              # 模型真实用量（input / output / cached / 成本）
