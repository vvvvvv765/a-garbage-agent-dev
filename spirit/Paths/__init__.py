"""
运行时目录解析（中立叶子）

**引擎不决定数据放哪，只负责解析。** 桌面壳 / 嵌入方可以显式注入，
也可以用环境变量；两样都没给才走默认规则。

优先级：
  1. Engine(home=...) 显式注入        —— 桌面壳用这个（同进程）
  2. 环境变量 SPIRIT_HOME             —— 子进程模式用这个
  3. 包目录旁边有 config.json（源码运行）→ 用包目录
  4. %LOCALAPPDATA%/Spirit（Windows）或 ~/.spirit
"""
import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent   # spirit/

_ROOT = None   # 显式注入的数据根；None = 没注入


def set_home(path=None):
    """显式指定数据根；传 None 撤销注入，回到环境变量 / 默认规则。"""
    global _ROOT
    if path:
        _ROOT = Path(path).expanduser().resolve()
        _ROOT.mkdir(parents=True, exist_ok=True)
    else:
        _ROOT = None
    return _ROOT


def home():
    """数据根目录（Session_Storage / Logs / spill 都放它下面）。"""
    if _ROOT is not None:
        return _ROOT
    env = os.environ.get("SPIRIT_HOME")
    if env:
        root = Path(env)
        root.mkdir(parents=True, exist_ok=True)
        return root
    if (PACKAGE / "config.json").exists():
        return PACKAGE
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "Spirit" if base else Path.home() / ".spirit"
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_file():
    return home() / "config.json"


def session_dir():
    return Path(os.environ.get("SPIRIT_SESSION_DIR") or (home() / "Session_Storage"))


def log_dir():
    return Path(os.environ.get("SPIRIT_LOG_DIR") or (home() / "Logs"))


def artifacts_dir():
    """能力体系的落盘产物区（框架托管，**不在工作区里**）。

    大输出 spill、下载的大文件、以后能力产出的文件都放这儿；
    工作区只放作业文件，框架产物不混进去。会话 / 日志仍是受保护区。
    """
    return home() / "Artifacts"


def spill_dir(relative="Session_Storage/spill"):
    """spill 目录：配置里是相对路径就挂在数据根下面，绝对路径原样用。"""
    path = Path(relative)
    return path if path.is_absolute() else home() / path
