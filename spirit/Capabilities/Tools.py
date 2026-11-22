"""外部侦察工具适配：ffuf / subfinder / dnsx / naabu / nmap 的统一查找与运行。"""
import os
import shutil
import subprocess
import time
from pathlib import Path

from Config import config

from .Executions import ExecutionCancelled, executions

# 安装包自带的工具目录（整个 agent 自包含，换机器也能用）
BUNDLED = Path(__file__).resolve().parents[1] / "shell" / "tools"

# 本机常见安装位置；顺序在配置 / 环境变量 / 自带 / PATH 之后
DEFAULT_DIRS = [
    Path(r"D:\kaifa\tools\bin"),
    Path(r"D:\kaifa\tools"),
    Path(r"D:\wangj\xinxisouji\wuying\ToolKit\ffuf\ffuf_2.1.0_windows_386"),
    Path(r"D:\wangj\Nmap\Nmap"),
]


def tool_path(name):
    key = str(name or "").lower()
    configured = str(config.get(f"tools.{key}", "") or "").strip()
    if configured:
        candidate = Path(configured)
        if candidate.exists():
            return candidate
    env = str(os.environ.get(f"SPIRIT_TOOL_{key.upper()}", "") or "").strip()
    if env and Path(env).exists():
        return Path(env)
    # 自带优先：安装包里的工具就是这台 agent 的一部分
    for suffix in (".exe", ""):
        candidate = BUNDLED / (key + suffix)
        if candidate.exists():
            return candidate
    found = shutil.which(key) or shutil.which(key + ".exe")
    if found:
        return Path(found)
    for folder in DEFAULT_DIRS:
        for suffix in (".exe", ""):
            candidate = folder / (key + suffix)
            if candidate.exists():
                return candidate
    return None


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=5)
        else:
            os.killpg(os.getpgid(proc.pid), 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run(name, args, timeout=120, cancel=None, cwd=None):
    """跑外部工具；返回 (stdout, stderr, code, problem)。"""
    exe = tool_path(name)
    if exe is None:
        return "", f"没有找到 {name}（配置 tools.{name} 指定路径）", None, "missing"
    proc = subprocess.Popen(
        [str(exe), *[str(arg) for arg in args]],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
        **(dict(start_new_session=True) if os.name != "nt" else {}),
    )
    try:
        executions.track(proc)
    except Exception:
        pass
    deadline = time.monotonic() + max(0.1, timeout)
    problem = ""
    try:
        while True:
            try:
                out, err = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel is not None and cancel.is_set():
                    problem = "cancelled"
                    break
                if time.monotonic() >= deadline:
                    problem = "timeout"
                    break
    finally:
        try:
            executions.untrack(proc)
        except Exception:
            pass
        if proc.poll() is None:
            _kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=3)
            except Exception:
                out, err = b"", b""
    text = (out or b"").decode("utf-8", errors="replace")
    errors = (err or b"").decode("utf-8", errors="replace")
    return text, errors, proc.returncode, problem


def checked(name, args, timeout=120, cancel=None, cwd=None):
    """跑工具并把失败变成异常；调用方负责捕获。"""
    out, err, code, problem = run(name, args, timeout, cancel, cwd)
    if problem == "cancelled":
        raise ExecutionCancelled("用户停止\n" + (out or err)[-2000:])
    if problem == "timeout":
        raise RuntimeError(f"{name} 超时（{timeout}s）\n{(out or err)[-2000:]}")
    if problem == "missing":
        raise RuntimeError(err)
    if code not in (0, None):
        raise RuntimeError(f"{name} 退出码 {code}\n{(err or out)[-2000:]}")
    return out, err
