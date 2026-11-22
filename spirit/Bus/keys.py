"""
中立表的 key 词表（总线的地址空间）

约定：
  BIOS / CPU 产出的东西 -> 登记在这里
  其他体系             -> 按 key 读取
"""

# 启动资源
LLM = "llm"                        # BIOS 产出的 responses 句柄
CAPABILITIES = "capabilities"      # 能力体系对象（CapabilitySystem）
DISK = "disk"                        # 硬盘体系（存储主体系，不可注销）
SESSION_LOCK = "session_lock"        # 会话切换 / 轮次启动共用的一把锁

# 体系 -> CPU 的报告
AGENT_START = "AgentStartSignal"   # BIOS 是否启动成功
USER_INPUT = "UserInputSignal"     # 用户输入体系的报告
GPU_SIGNAL = "GPUSignal"           # GPU 渲染体系的报告（本次出包并发出成没成）
MEMORY_SIGNAL = "MemorySignal"     # 内存体系的报告（本次处理流成没成）

# CPU -> 体系的控制
CPU_USER = "CPUUserInput"
CPU_MOD = "CPUModel"
CPU_THINKING = "CPUThinking"       # 思考开关（CPU 调度）
CPU_RENDER = "CPURender"           # 显示开关（指令：start / stop）
