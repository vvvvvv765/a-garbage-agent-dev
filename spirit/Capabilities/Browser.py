"""
browser 能力：把 ego lite 的 `ego-browser nodejs` 包成模型可调用的一个工具。

设计：
  - 模型写一段 Node ESM 脚本（ego 的代码型 API），一次调用做完多步；
  - 脚本通过 stdin 喂给 CLI，不经过 shell，Windows 上没有引号问题；
  - 每个 Spirit 会话固定一个 TaskSpace（`spiritTask()` 自动复用 spaceId）；
  - 脚本里用 `spiritShot(page, {path})` 截图，图片会随结果一起进上下文。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from Config import config
from Paths import home

from .Executions import ExecutionCancelled, executions
from .Output import CapabilityResult
from .Spec import CapabilitySpec

IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
IMAGE_MARK = "__SPIRIT_IMAGES__"
PAGE_MARK = "__SPIRIT_PAGE__"


def _candidates():
    """ego-browser 启动器位置：配置 > 环境变量 > PATH > Windows 默认安装目录。"""
    configured = str(config.get("engine.ego_browser", "") or "").strip()
    if configured:
        yield Path(configured)
    env = str(os.environ.get("SPIRIT_EGO_BROWSER", "") or "").strip()
    if env:
        yield Path(env)
    found = shutil.which("ego-browser")
    if found:
        yield Path(found)
    if os.name == "nt":
        for root in (
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        ):
            base = root / "Citro Labs" / "ego lite" / "Application"
            yield base / "ego-browser.exe"
            if base.is_dir():
                versions = sorted(
                    (item for item in base.iterdir() if item.is_dir()),
                    key=lambda item: item.stat().st_mtime,
                    reverse=True,
                )
                for folder in versions:
                    yield folder / "ego-browser.exe"
    elif os.name == "darwin":
        yield Path("/Applications/ego lite.app/Contents/Resources/ego-browser")
    else:
        yield Path("/opt/ego-lite/ego-browser")
    # 便携包自带的副本：换机器没装 ego 时用（新 profile，需要 onboarding）
    meipass = getattr(sys, "_MEIPASS", "")
    roots = [Path(__file__).resolve().parent.parent / "shell" / "ego-lite"]
    if meipass:
        roots.insert(0, Path(meipass) / "shell" / "ego-lite")
    for root in roots:
        yield root / "ego-browser.exe"
        if root.is_dir():
            versions = sorted(
                (item for item in root.iterdir() if item.is_dir()),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for folder in versions:
                yield folder / "ego-browser.exe"


def find_browser():
    for candidate in _candidates():
        try:
            if candidate and candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def _app_running():
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ego.exe", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return "ego.exe" in (result.stdout or "").lower()
        if os.name == "darwin":
            result = subprocess.run(
                ["pgrep", "-x", "ego"], capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        result = subprocess.run(
            ["pgrep", "-x", "ego"], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def _quick(exe, args, script, timeout):
    """不带执行上下文的短命令（健康检查 / 页面状态）。"""
    try:
        return subprocess.run(
            [str(exe), *args],
            input=(script.encode("utf-8") if script is not None else None),
            stdin=(None if script is not None else subprocess.DEVNULL),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,   # ego-browser 把脚本 console 写到 stderr
            timeout=timeout,
        )
    except Exception as error:
        return error


_HEALTH = {"at": 0.0, "onboarded": None, "error": "", "checking": False}
_HEALTH_LOCK = threading.Lock()


def _refresh_health(exe):
    result = _quick(exe, ["nodejs"], 'console.log("__SPIRIT_READY__");', 15)
    onboarded = None
    error = ""
    if isinstance(result, Exception):
        error = str(result)
    else:
        text = (result.stdout or b"").decode("utf-8", errors="replace")
        text += (result.stderr or b"").decode("utf-8", errors="replace")
        if "__SPIRIT_READY__" in text:
            onboarded = True
        elif "onboarding" in text.lower():
            onboarded = False
        else:
            error = text.strip()[:200] or f"exit {result.returncode}"
    with _HEALTH_LOCK:
        _HEALTH.update({
            "at": time.time(), "onboarded": onboarded,
            "error": error, "checking": False,
        })


def health():
    """快速健康快照：安装 / 应用 / onboarding。onboarding 检查在后台刷新。"""
    exe = find_browser()
    installed = exe is not None
    now = time.time()
    with _HEALTH_LOCK:
        stale = now - float(_HEALTH["at"] or 0) > 20
        checking = bool(_HEALTH["checking"])
        snapshot = dict(_HEALTH)
    if installed and stale and not checking:
        with _HEALTH_LOCK:
            _HEALTH["checking"] = True
        threading.Thread(
            target=_refresh_health, args=(exe,), name="ego-health", daemon=True
        ).start()
        snapshot["checking"] = True
    return {
        "installed": installed,
        "path": str(exe) if exe else "",
        "running": _app_running(),
        "onboarded": snapshot.get("onboarded"),
        "error": snapshot.get("error") or "",
        "checking": snapshot.get("checking", False),
    }


def _space_file(session_id):
    space = "spirit-" + (str(session_id or "primary").strip() or "primary")
    return space, home() / "browser" / f"{space}.space"


def _last_file(session_id):
    space, _ = _space_file(session_id)
    return home() / "browser" / f"{space}.last.json"


def _handoff_file(session_id):
    space, _ = _space_file(session_id)
    return home() / "browser" / f"{space}.handoff"


def _note_handoff(session_id, output):
    """浏览器要求用户处理权限 / 接管时留标记，下次调用自动 takeOver。"""
    text = str(output or "").lower()
    if (
        "permission prompt" in text
        or "user now controls" in text
        or "takeovertaskspace" in text
    ):
        try:
            path = _handoff_file(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        return True
    return False


def _record_last_shot(session_id, paths, images):
    if not images:
        return
    try:
        target = _last_file(session_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({
            "at": time.time(),
            "path": images[0].get("path") or paths[0],
            "upload": images[0].get("id") or "",
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _page_state(session_id, exe, timeout=15):
    """当前会话的 Space / 页面（有 Space 才查）。"""
    space, path = _space_file(session_id)
    if not path.exists():
        return None
    try:
        space_id = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not space_id:
        return None
    script = (
        "try {\n"
        f"const t = await taskSpace({json.dumps(space_id)});\n"
        "const pages = await t.pages();\n"
        "let url = '', title = '';\n"
        "if (pages.length) { url = await pages[0].url(); title = await pages[0].title(); }\n"
        f"console.log({json.dumps('__SPIRIT_STATE__')} + JSON.stringify({{space:t.spaceId,pages:pages.length,url,title}}));\n"
        "} catch (error) {\n"
        f"console.log({json.dumps('__SPIRIT_STATE__')} + JSON.stringify({{space:null,error:String(error)}}));\n"
        "}\n"
    )
    result = _quick(exe, ["nodejs"], script, timeout)
    if isinstance(result, Exception):
        return {"error": str(result)}
    text = (result.stdout or b"").decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        if line.startswith("__SPIRIT_STATE__"):
            try:
                return json.loads(line[len("__SPIRIT_STATE__"):])
            except Exception:
                return None
    return None


def last_screenshot(session_id):
    try:
        return json.loads(_last_file(session_id).read_text(encoding="utf-8"))
    except Exception:
        return None


def status(session_id):
    """给设置页 / API 的观察快照。"""
    base = health()
    deadline = time.monotonic() + 5
    while base.get("onboarded") is None and base.get("checking") and time.monotonic() < deadline:
        time.sleep(0.1)
        base = health()
    exe = find_browser()
    state = None
    if exe is not None and base.get("onboarded") is not False:
        state = _page_state(session_id, exe)
    last = last_screenshot(session_id)
    return {
        **base,
        "session": str(session_id or "primary"),
        "space": state,
        "last_screenshot": last,
        "attention": "permission" if _handoff_file(session_id).exists() else "",
    }


def start_app():
    """需要时拉起 ego lite（共享浏览器，不替用户关）。"""
    if _app_running():
        return True
    exe = find_browser()
    if exe is None:
        return False
    # 安装布局：Application/ego.exe + Application/<版本>/ego-browser.exe
    apps = [exe.parent / "ego.exe", exe.parent.parent / "ego.exe"]
    if os.name != "nt":
        apps = [exe.parent / "ego", exe.parent.parent / "ego"]
    app = next((item for item in apps if item.exists()), None)
    try:
        if app is not None:
            subprocess.Popen([str(app)], cwd=str(app.parent))
        elif os.name == "darwin":
            subprocess.Popen(["open", "-a", "ego lite"])
        else:
            return False
    except Exception:
        return False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _app_running():
            return True
        time.sleep(0.5)
    return False


def cleanup_stale_spaces():
    """开机补清理：只处理上次进程留下的 Space（30 秒前的），别碰刚创建的。"""
    return release_spaces(older_than=30)


def release_spaces(older_than=0):
    """Spirit 关机：关掉本机 Spirit 用过的 Space 里的页面（不动用户的标签页）。"""
    exe = find_browser()
    if exe is None or not _app_running():
        return 0
    released = 0
    now = time.time()
    for path in (home() / "browser").glob("*.space"):
        try:
            if older_than and now - path.stat().st_mtime < older_than:
                continue
            space_id = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not space_id:
            continue
        script = (
            "try {\n"
            f"const t = await taskSpace({json.dumps(space_id)});\n"
            "await t.finish({ keep: [] });\n"
            "console.log('__SPIRIT_RELEASED__');\n"
            "} catch (error) { console.log('__SPIRIT_RELEASE_FAIL__' + String(error)); }\n"
        )
        result = _quick(exe, ["nodejs"], script, 20)
        if isinstance(result, Exception):
            continue
        text = (result.stdout or b"").decode("utf-8", errors="replace")
        if "__SPIRIT_RELEASED__" in text:
            released += 1
            try:
                path.unlink()
            except OSError:
                pass
    return released


def _kill_tree(proc):
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True, timeout=5,
            )
        else:
            os.killpg(os.getpgid(proc.pid), 9)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _run(exe, args, script, timeout, cancel=None):
    """跑一次 CLI；返回 (output, code, problem)。problem: '' / timeout / cancelled。"""
    proc = subprocess.Popen(
        [str(exe), *args],
        stdin=subprocess.PIPE if script is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=None,
        **(dict(start_new_session=True) if os.name != "nt" else {}),
    )
    try:
        executions.track(proc)
    except Exception:
        pass
    data = script.encode("utf-8") if script is not None else None
    deadline = time.monotonic() + max(0.1, timeout)
    problem = ""
    chunks = []
    try:
        while True:
            try:
                out, _ = proc.communicate(input=data, timeout=0.2)
                chunks.append(out)
                break
            except subprocess.TimeoutExpired:
                data = None   # 已经写进 stdin，之后只等输出
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
                out, _ = proc.communicate(timeout=3)
                chunks.append(out)
            except Exception:
                pass
    text = b"".join(chunk for chunk in chunks if chunk).decode("utf-8", errors="replace")
    return text, proc.returncode, problem


def _attach_images(paths):
    """把截图复制进上传区，换成模型图像通路认识的 id。"""
    uploads = home() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    images = []
    for raw in paths:
        path = Path(str(raw or ""))
        suffix = path.suffix.lower()
        if suffix not in IMAGE_SUFFIX:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not data or len(data) > 8 * 1024 * 1024:
            continue
        digest = hashlib.sha256(data).hexdigest()[:32]
        ext = "jpg" if suffix == ".jpeg" else suffix.lstrip(".")
        name = f"{digest}.{ext}"
        target = uploads / name
        if not target.exists():
            temp = uploads / f".{name}.{os.getpid()}.tmp"
            try:
                temp.write_bytes(data)
                os.replace(temp, target)
            finally:
                try:
                    temp.unlink()
                except OSError:
                    pass
        images.append({
            "id": name,
            "mime": IMAGE_MIME[suffix],
            "path": str(path),
        })
    return images


def _strip_marker(text):
    """摘掉脚本末尾的页面 / 图片标记；返回 (正文, 图片路径列表, 页面状态)。"""
    paths = []
    page = None
    lines = str(text or "").splitlines()
    kept = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(IMAGE_MARK):
            try:
                parsed = json.loads(stripped[len(IMAGE_MARK):] or "[]")
                if isinstance(parsed, list):
                    paths.extend(parsed)
            except Exception:
                pass
            continue
        if stripped.startswith(PAGE_MARK):
            try:
                parsed = json.loads(stripped[len(PAGE_MARK):] or "{}")
                if isinstance(parsed, dict):
                    page = parsed
            except Exception:
                pass
            continue
        kept.append(line)
    return "\n".join(kept).strip(), paths, page


def _page_line(page):
    """把脚本末尾自动抓的页面状态压成一行，减少模型单独查询。"""
    if not isinstance(page, dict):
        return ""
    parts = []
    if page.get("title"):
        parts.append(str(page["title"]))
    if page.get("url"):
        parts.append(str(page["url"]))
    video = page.get("video")
    if isinstance(video, dict) and video.get("video"):
        parts.append(
            "video paused={} t={}/{} ready={}".format(
                video.get("paused"), video.get("currentTime"),
                video.get("duration"), video.get("readyState"),
            )
        )
    return ("[页面] " + " · ".join(parts)) if parts else ""


def _prelude(session_id):
    space = "spirit-" + (str(session_id or "primary").strip() or "primary")
    space_file = home() / "browser" / f"{space}.space"
    handoff_file = home() / "browser" / f"{space}.handoff"
    space_file.parent.mkdir(parents=True, exist_ok=True)
    return f"""
globalThis.SPIRIT_SPACE = {json.dumps(space)};
globalThis.__spiritImages = [];
globalThis.spiritShot = async (page, options = {{}}) => {{
  const path = await page.screenshot(options);
  globalThis.__spiritImages.push(path);
  return path;
}};
globalThis.spiritVideo = (page) => page.evaluate(() => {{
  const video = document.querySelector("video");
  if (!video) return {{ video: false }};
  return {{
    video: true,
    paused: video.paused,
    ended: video.ended,
    currentTime: Math.round(video.currentTime * 10) / 10,
    duration: Number.isFinite(video.duration) ? Math.round(video.duration) : null,
    readyState: video.readyState,
    muted: video.muted,
  }};
}});
globalThis.spiritTask = async () => {{
  // 供脚本末尾自动附页面 / 视频状态用
  const fs = await import("node:fs/promises");
  const file = {json.dumps(str(space_file))};
  const handoff = {json.dumps(str(handoff_file))};
  let id = "";
  try {{ id = (await fs.readFile(file, "utf8")).trim(); }} catch {{}}
  if (id) {{
    // 上次浏览器权限弹窗把控制权交给了用户；用户处理完后，这里自动接管
    try {{
      await fs.access(handoff);
      await takeOverTaskSpace(Number(id) || id);
      await fs.unlink(handoff);
    }} catch {{}}
    try {{
      const task = await taskSpace(id);
      globalThis.__spiritTaskRef = task;
      return task;
    }} catch {{}}
  }}
  const task = await taskSpace(SPIRIT_SPACE);
  try {{ await fs.writeFile(file, String(task.spaceId)); }} catch {{}}
  globalThis.__spiritTaskRef = task;
  return task;
}};
"""


class BrowserCapability:
    name = "browser"
    description = (
        "用 ego lite 浏览器操作网页（打开/点击/填表/抓取/截图）。"
        "传一段 Node ESM 脚本作为 code，顶层 await 可直接用；"
        "从 `const task = await spiritTask()` 开始，page = task.page(\"p1\")；"
        "常用：goto/snapshot/click/fill/screenshot/evaluate。"
        "一次脚本尽量做完多步（goto → 等加载 → 取信息/截图），不要拆成很多小调用。"
        "截图用 `await spiritShot(page, {path:\"绝对路径.png\"})`，图片会随结果进上下文。"
        "判断视频是否真的在播用 `await spiritVideo(page)`，不要靠截图猜。"
        "遇到浏览器权限弹窗会返回“等待用户处理”；用户点完允许后重跑同一段脚本即可，spiritTask() 会自动接管。"
        "不是 Playwright：不要用 locator/getByRole；完整 API 传 guide=true 获取。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Node ESM 脚本（可用 top-level await）"},
            "timeout": {
                "type": "integer",
                "description": "秒，默认 120，最大 300",
            },
            "guide": {
                "type": "boolean",
                "description": "true = 返回当前 ego-browser 版本的完整用法指南（首次使用先看）",
            },
        },
        "additionalProperties": False,
    }

    def spec(self):
        return CapabilitySpec(
            self.name, self.description, self.parameters,
            side_effect="external", trust="untrusted", timeout=330,
        )

    def run(self, arguments):
        exe = find_browser()
        if exe is None:
            return CapabilityResult(
                "没找到 ego-browser。先安装 ego lite（https://lite.ego.app/），"
                "或用配置 engine.ego_browser 指定 ego-browser.exe 的路径。",
                {"source": "browser（未安装）"},
                ok=False,
            )

        execution = executions.current()
        cancel = execution.cancel if execution is not None else None

        if arguments.get("guide"):
            output, code, problem = _run(exe, ["skill"], None, 60, cancel)
            if problem == "timeout":
                return CapabilityResult(
                    f"读取 ego-browser 指南超时\n{output}",
                    {"source": "browser"}, ok=False,
                )
            if problem == "cancelled":
                raise ExecutionCancelled("用户停止")
            return output or "ego-browser 没有输出指南"

        code = str(arguments.get("code") or "").strip()
        if not code:
            return CapabilityResult(
                "code 不能为空（先传 guide=true 看 API，再写脚本）",
                {"source": "browser"}, ok=False,
            )
        start_app()
        try:
            timeout = int(arguments.get("timeout") or config.get("engine.browser_timeout", 120))
        except (TypeError, ValueError):
            timeout = 120
        timeout = max(1, min(300, timeout))

        session_id = getattr(execution, "session_id", "") if execution is not None else ""
        script = (
            _prelude(session_id)
            + "\ntry {\n"
            + code
            + "\n} finally {\n"
            + "  try {\n"
            + "    const ref = globalThis.__spiritTaskRef;\n"
            + "    if (ref) {\n"
            + "      const pages = await ref.pages();\n"
            + "      if (pages.length) {\n"
            + "        const p = pages[0];\n"
            + "        const video = await p.evaluate(() => {\n"
            + "          const v = document.querySelector('video');\n"
            + "          if (!v) return { video: false };\n"
            + "          return { video: true, paused: v.paused, ended: v.ended,\n"
            + "            currentTime: Math.round(v.currentTime * 10) / 10,\n"
            + "            duration: Number.isFinite(v.duration) ? Math.round(v.duration) : null,\n"
            + "            readyState: v.readyState, muted: v.muted };\n"
            + "        });\n"
            + f"        console.log({json.dumps(PAGE_MARK)} + JSON.stringify({{ title: await p.title(), url: await p.url(), video }}));\n"
            + "      }\n"
            + "    }\n"
            + "  } catch (error) {}\n"
            + f"  console.log({json.dumps(IMAGE_MARK)} + JSON.stringify(globalThis.__spiritImages || []));\n"
            + "}\n"
        )
        output, status, problem = _run(exe, ["nodejs"], script, timeout, cancel)
        if problem == "cancelled":
            detail = output.strip()
            raise ExecutionCancelled(
                "用户停止" + (f"\n取消前已捕获的输出：\n{detail}" if detail else "")
            )
        content, paths, page = _strip_marker(output)
        page_line = _page_line(page)
        if page_line:
            content = (content + "\n" + page_line).strip() if content else page_line
        handoff = _note_handoff(session_id, output)
        if handoff:
            return CapabilityResult(
                content
                + "\n\n浏览器把控制权交给了用户（权限弹窗 / 接管状态）。"
                "请用户在 ego lite 窗口里处理完，然后**重跑同一段脚本**；"
                "spiritTask() 会自动 takeOverTaskSpace，不需要额外步骤。",
                {"source": "browser（等待用户处理权限）", "attention": "permission"},
                ok=False,
            )
        if problem == "timeout":
            return CapabilityResult(
                f"browser 脚本超时（{timeout} 秒），相关进程已终止"
                f"\n可在 timeout 参数里调大（1–600 秒）\n{content}",
                {"source": "browser"}, ok=False,
            )
        ok = status in (None, 0)
        if not ok:
            mark = f"[exit {status}]"
            content = f"{content}\n{mark}" if content else mark
        if not content:
            content = "（脚本没有输出）"
        if ok:
            try:
                _handoff_file(session_id).unlink()
            except OSError:
                pass

        images = _attach_images(paths)
        meta = {"source": "browser（网页内容）"}
        if images:
            _record_last_shot(session_id, paths, images)
            return CapabilityResult(
                content + f"\n（附上 {len(images)} 张截图）",
                {**meta, "images": images, "kind": "image"},
                ok=ok,
            )
        return CapabilityResult(content, meta, ok=ok)

    def dispose(self):
        """Spirit 关机：释放本机 Spirit 用过的 Space（不杀用户的浏览器）。"""
        try:
            released = release_spaces()
            if released:
                from Log import log
                log.info("Browser", f"released {released} ego space(s)")
        except Exception:
            pass
