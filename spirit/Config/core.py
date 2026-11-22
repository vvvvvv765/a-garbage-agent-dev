"""
配置体系（中立工具）：读取 spirit/config.json。

- 文件不存在 / 解析失败 → 用默认值（不让配置问题把主程序带崩）
- 各部分按自己的需要读：适配层读 llm，CPU 读 max_steps，GPU 读上下文策略
"""
import copy
import json
from contextlib import contextmanager
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from Paths import config_file

DEFAULTS = {
    "llm": {
        "provider": "openai",
        "provider_id": "deepseek",
        "model": "deepseek-Flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "",               # 直接写在配置里的 Key（空 = 读 api_key_env）
        "api_key_env": "DEEPSEEK_API_KEY",
        "providers": [
            {
                "id": "deepseek",
                "name": "DeepSeek",
                "kind": "openai",
                "auth": "token",
                "category": "cn_official",
                "base_url": "https://api.deepseek.com",
                "endpoints": ["https://api.deepseek.com"],
                "api_key": "",
                "api_key_env": "DEEPSEEK_API_KEY",
                "api_key_url": "https://platform.deepseek.com/api_keys",
                "models": ["deepseek-Flash", "deepseek-v4-flash"],
                "pricing": {"input": 0, "output": 0, "currency": "CNY"},
                "website": "https://platform.deepseek.com",
                "notes": "",
                "icon": "deepseek.svg",
                "icon_color": "#4d6bfe",
                "in_failover_queue": False,
                "context_window": 128000,
                "max_tokens": 8192,
            }
        ],
        "pricing": {"input": 0, "output": 0, "currency": "CNY"},
        "reasoning": "high",     # 思考等级：low / high / max（DeepSeek 官方档位）
        "timeout": 120,          # 单次 HTTP 请求超时（秒）；SDK 自带重试已关闭，重试只归 Reconnect
        "context_window": 128000,
        "max_tokens": 8192,       # 单次输出上限（每家可覆盖）
        "search_base_url": "https://api.deepseek.com/anthropic/v1",  # 搜索走 Anthropic 兼容端点
        "search_model": "deepseek-v4-flash",
        "search_provider": "deepseek",   # deepseek | tavily
        "tavily_api_key": "",
        "tavily_api_key_env": "TAVILY_API_KEY",
    },
    "engine": {
        "max_steps": 0,     # <=0 = 不限（靠停止 / 重复拦截 / 预算兜底）
        "thinking": False,       # 思考开关（CPU 统一调度）
        "restore": True,         # 启动时恢复最新一次会话
        "system_prompt": "",             # 非空时覆盖下面的文件
        "system_prompt_file": "Prompts/engine.md",
        "scenario": "daily",             # 场景：daily | pentest | 自定义
        "pentest_scope": [],             # 渗透场景的授权目标（域名 / IP / URL 前缀）；本机与私网默认允许
        "project_context": "",
        "tool_output_inline": 12000,
        "bash_timeout": 30,          # bash 默认超时（秒）；单条命令可用 timeout 参数覆盖
        "browser_timeout": 120,      # ego-browser 脚本默认超时（秒）
        "ego_browser": "",           # ego-browser 启动器路径；空 = 自动查找
        "keep_recent_tool_results": 5,
        "summarize": True,          # 预算仍超时做摘要压缩
        "keep_recent_turns": 2,     # 摘要时保留最近几轮原文
        "tool_workers": 4,
        "capability_timeout": 60,   # 单次能力调用的默认超时（秒）；能力可自己声明
        "capability_queue": 32,     # 同时排队 + 执行的能力上限；超了直接拒绝回模型
        "capability_isolation": False,  # 能力进程隔离（部署配置可开；测试默认关）
        "capability_workers": 2,        # 隔离 worker 数
        "log_max_bytes": 5242880,   # 单个日志文件上限（5MB，超了轮转）
        "log_backups": 3,           # 保留几份历史日志
        "access": "workspace",     # readonly | workspace（能碰什么）
        "approval": "auto",          # ask | auto；默认自动（2026-11-22 他定：不要逐条问）
        "approval_timeout": 30,     # 等用户审批的秒数，超时按拒绝（工具 30 秒没结果就该有问题）
        "untrusted_policy": "confirm",  # 不可信内容之后的高风险调用：warn | confirm | block
        "max_turn_tokens": 0,       # 单轮 token 预算；0 = 不限
        "max_session_tokens": 0,    # 会话 token 预算；0 = 不限
        "max_turn_cost": 0,         # 单轮成本预算（按提供商价格表）；0 = 不限
        "max_session_cost": 0,      # 会话成本预算；0 = 不限
        "repeat_limit": 3,          # 同参数调用重复几次后拦截；0 = 关闭
        "max_images_per_request": 8,  # 单次请求最多几张工具图片（同 id 去重；0 = 不限）
        "failover": {               # 故障转移（照抄 cc-switch 的队列 + 熔断概念）
            "enabled": False,       # 关着不动：请求失败时按队列换下一家重试
            "prefer_primary": True, # 新的一轮里主家恢复就回切（一轮只试一次）
            "threshold": 4,         # 连续失败几次后熔断这家
            "cooldown": 60,         # 熔断多少秒后半开（到点自动重试）
            "total_timeout": 180,   # 整轮故障转移的总时限（秒）；0 = 不限
        },
        "sandbox": {
            "workspace_only": False,      # 文件能力不再限制在工作区（沙箱 = sandboxRun 能力）
            "allow_paths": [],            # 额外允许的绝对路径（如 CTF 目录）
            "deny_paths": [               # 永远拒绝（~ 会展开）
                "~/.ssh", "~/.aws", "~/.gnupg",
                "~/.git-credentials", "~/.npmrc", "~/.docker/config.json",
            ],
            "home_is_workspace": True,    # bash 的 HOME/USERPROFILE 指到工作区
            "scrub_env": True,            # 去掉 Key / SPIRIT_* / 云凭据环境变量
            "auto_allow_outside": False,  # 旧开关（保留兼容，界面已移除）
            "wsl_distro": "kali-linux",   # sandboxRun 用的 WSL 发行版
            "isolation_timeout": 120,     # sandboxRun 默认超时（秒）
        },
        "workdir": "",              # 当前工作目录；留空 = 引擎启动目录
        "default_workspace": "",    # 默认工作区（桌面壳首次启动写）
        "workspaces": [],           # 用户添加的工作区 [{name, path}]
        "spill_dir": "",                 # 空 = 工作区/tmp/spill（会话目录受保护，模型读不回来）
        "budget_ratio": 0.8,
        "bash_path": "",            # 留空 = spirit/shell/PortableGit/bin/bash.exe
        "web_host": "127.0.0.1",
        "web_port": 5000,
    },
    "tools": {
        "ffuf": "",                 # 留空 = 自动查找（PATH / D:\kaifa\tools\bin / 常见安装位置）
        "subfinder": "",
        "dnsx": "",
        "naabu": "",
        "nmap": "",
    },
    "assets": {
        "platforms": {
            "fofa": {"enabled": False, "key": "", "base_url": "", "status": {}},
            "quake": {"enabled": False, "key": "", "base_url": "", "status": {}},
            "hunter": {"enabled": False, "key": "", "base_url": "", "status": {}},
        },
    },
}


class Config:
    def __init__(self):
        self.__data = copy.deepcopy(DEFAULTS)
        self.__loaded = False
        self.degraded = False          # True = 读到了坏配置，已改名留档
        self.load_message = ""
        self.repairs = []              # 上次 load 修正过类型不符的字段（诊断用）
        # 写配置是并发面：Flask 多线程下 保存提供商 / 审批模式 / 场景 可能同时进来
        self.__lock = threading.RLock()

    @contextmanager
    def mutation(self):
        """读-改-写整段拿同一把锁（providers 的增删改 / 排序 / 切换用）。"""
        if not self.__loaded:
            self.load()
        with self.__lock:
            yield self.__data

    def load(self, path=None):
        """（重新）读配置；path 空 = 当前数据根下的 config.json。

        Engine 构造时调用：先定数据根，再读那个根里的配置。
        """
        data = copy.deepcopy(DEFAULTS)
        target = Path(path) if path else config_file()
        self.degraded = False
        self.load_message = ""
        self.repairs = []
        try:
            with open(target, encoding="utf-8") as file:
                user = json.load(file)
            if not isinstance(user, dict):
                raise ValueError("config.json 顶层不是对象")
            self.__merge(data, user)
            # 旧扁平配置（llm 下只有 provider / base_url / Key）没有 providers 列表：
            # 不能拿 DEFAULTS 里的示例 providers 盖住它，否则 legacy 字段永远不生效
            user_llm = user.get("llm")
            if isinstance(user_llm, dict) and "providers" not in user_llm:
                data.get("llm", {}).pop("providers", None)
            # 字段类型归一：JSON 结构错有下面的兜底；**字段类型错**（例如
            # context_window: "big"）以前会把 int("big") 一路带到 Providers / GPU，
            # 轻则接口 500，重则引擎起不来。只修形状对得上的位置。
            repairs = self.__normalize_types(data)
            if repairs:
                shown = "、".join(repairs[:3])
                more = f" 等 {len(repairs)} 处" if len(repairs) > 3 else ""
                self.load_message = f"配置里有类型不符的字段（{shown}{more}），已按默认值修正"
                self.repairs = list(repairs)
        except FileNotFoundError:
            pass
        except Exception as error:
            # 坏配置不能"静默用默认"：下一次 save 会把默认值整份盖回去。
            # 先把坏文件改名留档，再降级运行；用户能从这里找回 Key / 提供商。
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = target.with_name(f"{target.name}.corrupt-{stamp}")
            try:
                target.rename(backup)
                self.load_message = f"配置损坏，已备份为 {backup.name}，本次使用默认值"
            except OSError as move_error:
                self.load_message = f"配置损坏且无法备份（{move_error}），本次使用默认值"
            self.degraded = True
        with self.__lock:
            self.__data = data
            self.__loaded = True
        return data

    def __merge(self, base, overlay):
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                self.__merge(base[key], value)
            else:
                base[key] = value

    # ---------- 字段类型归一 ----------
    def __normalize_types(self, data):
        """按 DEFAULTS 的形状修数字 / 布尔字段；字符串、列表、自定义字段原样保留。

        只修“默认值是数字 / 布尔”的位置——别的地方交给各体系自己校验。
        返回修正过的字段路径（给 load_message / 测试看）。
        """
        repairs = []
        self.__repair_node(copy.deepcopy(DEFAULTS), data, "", repairs)
        return repairs

    @staticmethod
    def __repair_node(base, value, path, repairs):
        if isinstance(base, dict):
            if not isinstance(value, dict):
                repairs.append(f"{path or '顶层'} 应为对象")
                return copy.deepcopy(base)
            for key, default in base.items():
                if key in value:
                    child = f"{path}.{key}" if path else key
                    value[key] = Config.__repair_node(default, value[key], child, repairs)
            return value
        if isinstance(base, list):
            return value          # providers 之类的列表内容不动
        if isinstance(base, bool):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in {"true", "1", "yes", "on"}:
                    return True
                if lowered in {"false", "0", "no", "off"}:
                    return False
            if isinstance(value, int) and value in (0, 1):
                return bool(value)
            repairs.append(f"{path} 应为布尔")
            return base
        if isinstance(base, int):
            number = value
            if isinstance(number, str):
                try:
                    number = int(number.strip())
                except ValueError:
                    try:
                        number = float(number.strip())
                    except ValueError:
                        number = None
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                repairs.append(f"{path} 应为整数")
                return base
            return int(number)
        if isinstance(base, float):
            try:
                return float(value)
            except (TypeError, ValueError):
                repairs.append(f"{path} 应为数字")
                return base
        return value

    def get(self, path, default=None):
        """按 a.b.c 取值。"""
        if not self.__loaded:
            self.load()
        node = self.__data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path, value):
        """运行期覆盖一个值；需要持久化时再调 save()。"""
        if not self.__loaded:
            self.load()
        parts = path.split(".")
        with self.__lock:
            node = self.__data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value

    def save(self):
        """把当前配置写回数据根下的 config.json（含界面里改的提供商 / Key）。

        - **锁内深拷贝快照**：dump 的时候别的线程再 set，也不会撞
          “dictionary changed size during iteration”
        - **tmp + os.replace**：写一半崩了也不会留下半截 config.json
          （半截文件的后果是下次 load 静默回落到 DEFAULTS，配置全丢）
        """
        target = config_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.__lock:
            snapshot = copy.deepcopy(self.__data)
        # 每次成功覆盖前留一份上一版（只留一份，够用且不占地方）
        if target.exists():
            try:
                shutil.copy2(target, target.with_name(f"{target.name}.bak"))
            except OSError:
                pass
        temp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temp, "w", encoding="utf-8") as file:
                json.dump(snapshot, file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            # Windows：目标文件被别人打开（编辑器 / 杀毒 / 测试读者）时 replace 会拒绝访问。
            # 最多等 2 秒；真等不到就抛出去，让调用方看到明确错误（不要静默退回非原子写）。
            last_error = None
            for _ in range(100):
                try:
                    os.replace(temp, target)
                    break
                except PermissionError as error:
                    last_error = error
                    time.sleep(0.02)
            else:
                raise last_error
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except OSError:
                    pass
        return str(target)


config = Config()
