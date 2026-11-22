"""
sandboxRun 能力：在一台一次性的隔离环境里跑命令（WSL + bubblewrap）。

定位（他的设计）：**沙箱不是全局笼子，而是一个能力**——
模型自己判断什么时候该把东西关进去跑：下载的脚本、靶场 payload、来源不明的代码。
普通任务直接 bash，不隔离。

隔离边界：
  - 每次调用一个独立临时工作目录（数据根/Sandbox/<id>），宿主文件、/mnt、/home 都看不见
  - 系统目录只读；/tmp、/run 是临时内存盘
  - 默认断网（network=true 才共享 WSL 网络）
  - 共享 Linux 内核：挡文件系统与网络，不挡内核级逃逸，不是虚拟机
"""
import os
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from Cancel import token as cancel_token
from Config import config
from Paths import home

from .Executions import executions
from .Spec import CapabilitySpec

CREATE_NO_WINDOW = 0x08000000
MAX_OUTPUT = 60_000


def _wsl_exe():
    found = shutil.which("wsl")
    if found:
        return found
    candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wsl.exe"
    return str(candidate) if candidate.exists() else ""


def _to_wsl_path(path):
    """Windows 路径 → WSL 路径（D:\\x → /mnt/d/x）。"""
    resolved = Path(path).resolve()
    drive = resolved.drive
    if drive:
        rest = str(resolved)[len(drive):].replace("\\", "/").lstrip("/")
        return f"/mnt/{drive[0].lower()}/{rest}"
    return str(resolved).replace("\\", "/")


def _bwrap_script(command, scratch_wsl, network, timeout, sid):
    parts = [
        "bwrap",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--ro-bind-try", "/opt", "/opt",
        "--bind", scratch_wsl, "/work",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        "--dir", "/home",
        "--dir", "/root",
        "--dir", "/var",
        "--dir", "/var/tmp",
        "--chdir", "/work",
        "--dev", "/dev",
        "--proc", "/proc",
        "--cap-drop", "ALL",
        "--die-with-parent",
    ]
    if not network:
        parts.append("--unshare-net")
    parts += [
        "--", "env", f"SPIRIT_SANDBOX_ID={sid}",
        "timeout", f"{int(timeout)}s", "sh", "-lc", command,
    ]
    return " ".join(shlex.quote(item) for item in parts)


class IsolatedRunCapability:
    name = "sandboxRun"
    description = (
        "在一台一次性隔离环境里跑命令：只能看到临时工作目录，看不到宿主文件，默认断网。"
        "用于来源不明的脚本、下载的代码、靶场 payload。"
        "普通、自己写的、可信的命令直接用 bash，不要滥用。"
        "返回输出和退出码；文件留在沙箱工作目录里，脚本自己写文件也落在这里。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令；cwd 是隔离环境的 /work",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 120，最大 600）",
            },
            "network": {
                "type": "boolean",
                "description": "是否允许联网（默认 false）",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(
            self.name,
            self.description,
            self.parameters,
            side_effect="read",   # 隔离环境内执行：不触发审批，批内可并行
            trust="untrusted",
            max_inline=8000,
            timeout=620,
        )

    def run(self, arguments):
        command = str(arguments.get("command") or "").strip()
        if not command:
            return "command 不能为空"

        wsl = _wsl_exe()
        if not wsl:
            return "这台机器上没有 WSL（wsl.exe），sandboxRun 不可用；普通命令请用 bash"

        distro = str(config.get("engine.sandbox.wsl_distro", "kali-linux") or "kali-linux")
        try:
            timeout = int(arguments.get("timeout") or config.get("engine.sandbox.isolation_timeout", 120))
        except (TypeError, ValueError):
            timeout = 120
        timeout = max(5, min(600, timeout))
        network = bool(arguments.get("network"))

        # 每次调用独立目录：并行的 sandboxRun 不会互相看到文件
        sid = f"spirit-sandbox-{uuid.uuid4().hex[:12]}"
        scratch = Path(home()) / "Sandbox" / sid
        scratch.mkdir(parents=True, exist_ok=True)
        scratch_wsl = _to_wsl_path(scratch)
        script = _bwrap_script(command, scratch_wsl, network, timeout, sid)

        argv = [wsl, "-d", distro, "--", "bash", "-lc", script]
        try:
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            return f"沙箱启动失败：{error}"

        chunks = []

        def _drain():
            try:
                for chunk in iter(lambda: process.stdout.read(4096), b""):
                    chunks.append(chunk)
            except Exception:
                pass

        reader = threading.Thread(target=_drain, daemon=True)
        reader.start()

        current = executions.current()
        cancel = current.cancel if current is not None else cancel_token
        deadline = time.monotonic() + timeout
        reason = ""
        while process.poll() is None:
            if cancel.is_set():
                reason = "已取消"
                break
            if time.monotonic() >= deadline:
                reason = f"沙箱执行超时（{timeout} 秒）"
                break
            time.sleep(0.2)

        if reason:
            self._kill_tree(process)
            cleaned = self._cleanup_sandbox(wsl, distro, sid)
            reader.join(0.5)
            suffix = "已终止" if cleaned else "已请求终止（沙箱内可能仍有残留）"
            return f"{reason}，{suffix}"

        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._kill_tree(process)
        reader.join(1.0)
        text = _decode(b"".join(chunks)).strip()
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n…（输出过长，已截断）"
        if not text:
            text = "（无输出）"
        code = process.returncode
        note = f"\n\n[沙箱] 退出码 {code} · 工作目录 {scratch}"
        if "bwrap: " in text and code != 0:
            note += " · 检查 WSL 里是否装了 bubblewrap（bwrap）"
        return text + note

    @staticmethod
    def _kill_tree(process):
        try:
            if process.poll() is not None:
                return
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                )
            else:
                try:
                    os.killpg(os.getpgid(process.pid), 9)
                except OSError:
                    process.kill()
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        try:
            process.wait(timeout=3)
        except Exception:
            pass

    @staticmethod
    def _cleanup_sandbox(wsl, distro, sid):
        """只杀本次调用的 bwrap（按唯一标记匹配），不碰别人的进程。"""
        pattern = f"[s]pirit-sandbox-{sid.split('spirit-sandbox-')[-1]}"
        try:
            result = subprocess.run(
                [wsl, "-d", distro, "--", "bash", "-lc",
                 f"pkill -f {shlex.quote(pattern)} || true"],
                capture_output=True,
                timeout=5,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return result.returncode in (0, 1)
        except Exception:
            return False


def _decode(data):
    if not data:
        return ""
    for encoding in ("utf-8", "gbk", "utf-16"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, AttributeError):
            continue
    return data.decode("utf-8", errors="replace")
