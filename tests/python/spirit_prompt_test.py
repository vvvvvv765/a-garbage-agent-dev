"""提示词工程回归：底座说明书 + 场景增量 + 运行时上下文 + 体量预算。

2026-11-19 要求："提示词工程稳步推进，要让大模型知道怎么使用这台 agent 计算机"。
底座答"这台计算机是什么、有什么、权限怎么工作、被拒怎么办"；场景答"这次干什么、怎么干"。
"""
import os
import sys
import tempfile
from pathlib import Path

root = os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit")
sys.path.insert(0, root)
for name in ("SPIRIT_HOME", "SPIRIT_SESSION_DIR", "SPIRIT_LOG_DIR", "SPIRIT_WORKDIR"):
    os.environ.pop(name, None)

import Scenarios  # noqa: E402
from Config import config  # noqa: E402
from Engine import Engine  # noqa: E402
from GPU.core import _instructions, _runtime_context  # noqa: E402

base = Path(root, "Prompts", "engine.md").read_text(encoding="utf-8")

# ---------- 1. 底座：该教的都教了 ----------
for heading in ("这台计算机有什么", "权限：两个轴", "沙箱", "不可信内容", "怎么用这些能力", "回答"):
    assert heading in base, f"底座缺少小节：{heading}"
for word in ("查看", "可修改", "询问", "自动", "被拒绝是", "不要用相同参数重试"):
    assert word in base, f"底座缺少关键词：{word}"
assert "引擎" not in base, "底座里还有旧口径「引擎」"
print("1. 底座小节 ok")

# ---------- 2. 场景增量：术语同步、无旧口径 ----------
for name in ("daily", "pentest"):
    prompt = Scenarios.prompt_for(name)
    assert "引擎" not in prompt, f"{name} 场景还有旧口径"
    assert "可访问的路径" in prompt, f"{name} 场景没提「可访问的路径」"
    if name == "daily":
        assert "查看" in prompt and "readFile" in prompt
    else:
        assert "查看" in prompt and "可修改" in prompt
print("2. 场景增量 ok")

# ---------- 3. GPU 拼装：底座 + 场景 ----------
home = Path(tempfile.mkdtemp(prefix="spirit-prompt-home-"))
work = Path(tempfile.mkdtemp(prefix="spirit-prompt-work-"))
engine = Engine(home=home, workdir=work)

config.set("engine.scenario", "daily")
daily_text = _instructions()
assert "这台计算机有什么" in daily_text, daily_text[:200]
assert "# 日常场景" in daily_text, "日常场景没拼进去"

engine.use_scenario("pentest")   # 空会话，允许切换
pentest_text = _instructions()
assert "# 渗透测试场景" in pentest_text
assert "日常场景" not in pentest_text
assert "授权与范围（必须遵守）" in pentest_text
print("3. 拼装 ok")

# ---------- 4. 运行时上下文：变量都在 ----------
config.set("engine.pentest_scope", ["example.com", "*.example.com"])
ctx = _runtime_context()
for needle in ("当前运行时上下文", str(work) if str(work) in ctx else "工作目录",
               "工作范围", "操作模式", "今天",
               "渗透授权范围", "example.com"):
    assert needle in ctx, f"运行时上下文缺少：{needle} / {ctx}"
engine.set_access("readonly")
assert "查看" in _runtime_context()
engine.set_access("workspace")
engine.set_approval("auto")
assert "自动" in _runtime_context()
engine.set_approval("ask")
print("4. 运行时上下文 ok")

# ---------- 5. 体量预算（防止提示词无限膨胀） ----------
base_len = len(base)
assert base_len < 6000, f"底座太长：{base_len}"
for name in ("daily", "pentest"):
    length = len(Scenarios.prompt_for(name))
    assert length < 7000, f"{name} 场景太长：{length}"   # 渗透提示词按专业红队重写，放宽到 7000
print(f"5. 体量预算 ok（底座 {base_len} 字，场景 "
      f"{len(Scenarios.prompt_for('daily'))} / {len(Scenarios.prompt_for('pentest'))} 字）")

print("ALL PROMPT TESTS PASSED")
