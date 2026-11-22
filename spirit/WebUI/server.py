"""
Web UI 适配器：把渲染出口和输入源接到浏览器。

它自己不是体系，也**不碰引擎内部**：只通过 Engine 门面接线
（attach_display / set_input_source / list_sessions / settings ...）。
出、入两块分别封装在 WebUI/Output.py、WebUI/Input.py。

运行：cd spirit && python -m WebUI.server（或 python -m MoBo.main web）
页面：http://127.0.0.1:5000
"""
import base64
import binascii
import json
import os
import queue
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, request, send_from_directory

from Config import Providers, config
from Disk import disk
from Engine import Engine
from Paths import session_dir
from WebUI.Input import attach as attach_input
from WebUI.Input import inputs
from WebUI.Output import attach as attach_output
from WebUI.Output import publish, subscribe, unsubscribe

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

# 本地控制面的令牌：本机其它进程 / 网页拿不到这个值（页面加载时注入 meta）
API_TOKEN = os.environ.get("SPIRIT_API_TOKEN") or uuid.uuid4().hex
AUTH_DISABLED = os.environ.get("SPIRIT_WEB_AUTH", "").strip().lower() in {"0", "off", "false"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


def _host_of(value):
    try:
        text = str(value or "")
        if "://" not in text:
            text = "//" + text
        return (urlsplit(text).hostname or "").lower()
    except Exception:
        return ""


def _allowed_hosts():
    hosts = set(LOOPBACK_HOSTS)
    bind = (os.environ.get("SPIRIT_WEB_HOST")
            or str(config.get("engine.web_host", "") or "")).strip().lower()
    if bind and bind not in {"0.0.0.0", "::"}:
        hosts.add(bind)
    extra = os.environ.get("SPIRIT_WEB_ALLOW_HOST", "")
    for item in extra.split(","):
        item = item.strip().lower()
        if item:
            hosts.add(item)
    return hosts


@app.before_request
def _guard_api():
    """DNS rebinding + 本机其它进程。

    - **所有路由**都校验 Host（首页会把令牌写进 HTML，不能让 rebinding 读到）
    - `/api/*` 要令牌：普通请求用 `X-Spirit-Token`；只有 SSE 允许 `?token=`（EventSource 设不了头）
    - 带 Origin 的跨站请求直接拒绝（令牌泄露后的最后一道）
    """
    if _host_of(request.host) not in _allowed_hosts():
        return {"ok": False, "error": "host not allowed"}, 403
    if not request.path.startswith("/api/"):
        return None
    if AUTH_DISABLED:
        return None
    # 健康检查不带令牌（桌面壳靠它判断引擎起没起）；其余 /api/* 一律要令牌
    if request.path == "/api/status":
        return None
    token = request.headers.get("X-Spirit-Token") or ""
    if not token and (
        request.path == "/api/events"
        or request.path.startswith("/api/upload/")
    ):
        token = request.args.get("token") or ""
    if token != API_TOKEN:
        return {"ok": False, "error": "unauthorized"}, 401
    origin = request.headers.get("Origin")
    if origin and _host_of(origin) not in _allowed_hosts():
        return {"ok": False, "error": "origin not allowed"}, 403
    return None


def session_file(path):
    """校验会话路径：必须落在会话目录里（load / rename / delete 共用）。"""
    target = Path(str(path or "")).expanduser().resolve()
    root = Path(session_dir()).resolve()
    if target != root and root not in target.parents:
        raise ValueError("会话文件不在会话目录里")
    return target


def test_client():
    """测试用客户端：自动带令牌与 loopback Host。"""
    client = app.test_client()
    try:
        client.environ_base["HTTP_X_SPIRIT_TOKEN"] = API_TOKEN
        client.environ_base["HTTP_HOST"] = "127.0.0.1"
    except Exception:
        pass
    return client


_engine = None
_started = False
_lock = threading.Lock()

# 等用户审批的请求：id -> (答案队列, 请求内容)
_pending = {}
_pending_lock = threading.Lock()


def _approver(request):
    """引擎的审批回调：把请求推给页面，等用户点 允许 / 拒绝（超时按拒绝）。"""
    from WebUI.Output import has_subscribers

    if not has_subscribers():
        # 没有打开的界面：没人能点允许，别死等——直接拒绝并说明
        return False, "没有打开的界面，无人审批，按拒绝处理（可切到自动模式）"
    request_id = uuid.uuid4().hex
    answer = queue.Queue(maxsize=1)
    with _pending_lock:
        _pending[request_id] = (answer, request)

    publish({
        "type": "approval_request",
        "id": request_id,
        "call_id": request.get("call_id", ""),
        "name": request.get("name", ""),
        "arguments": request.get("arguments", ""),
        "mode": request.get("mode", ""),
        "untrusted": bool(request.get("untrusted")),
        "source": request.get("source", ""),
        "kind": request.get("kind", ""),
        "path": request.get("path", ""),
        "command": request.get("command", ""),
        "reason": request.get("reason", ""),
        "session": request.get("session", ""),
        "session_title": request.get("session_title", ""),
    })

    timeout = float(config.get("engine.approval_timeout", 30))
    timed_out = False
    try:
        answer_value = answer.get(timeout=max(1.0, timeout))
    except queue.Empty:
        answer_value = False
        timed_out = True
    finally:
        with _pending_lock:
            _pending.pop(request_id, None)

    if timed_out:
        publish({
            "type": "approval_resolved",
            "id": request_id,
            "allow": False,
            "reason": "审批超时",
        })
        return False, "审批超时，按拒绝处理"
    remember = False
    if isinstance(answer_value, dict):
        allow = bool(answer_value.get("allow"))
        remember = bool(answer_value.get("remember"))
    else:
        allow = bool(answer_value)
    if allow:
        return True, "用户允许", ("session" if remember else "once")
    return False, "用户拒绝执行该能力"


def _deny_pending(reason, session=None):
    """拒绝还在等的审批；传 session 时只拒这个会话的（停止当前会话用）。"""
    with _pending_lock:
        items = list(_pending.items())
    if session is not None:
        wanted = str(session or "primary")
        items = [
            (request_id, item) for request_id, item in items
            if str((item[1] or {}).get("session") or "primary") == wanted
        ]
    for request_id, (answer, _request) in items:
        try:
            answer.put_nowait(False)
        except queue.Full:
            continue
        publish({
            "type": "approval_resolved",
            "id": request_id,
            "allow": False,
            "reason": reason,
        })

# 引擎起之前的默认设置；起来之后以引擎状态为准
# 档位按 DeepSeek 的思考等级：low / high / max（medium 等旧值按官方别名映射）
_EFFORT_ALIASES = {"minimal": "low", "medium": "high", "xhigh": "high", "ultra": "max"}
_EFFORTS = {"low", "high", "max"}


def _normalize_effort(value, default="high"):
    value = _EFFORT_ALIASES.get(str(value or "").lower(), str(value or "").lower())
    return value if value in _EFFORTS else default


_settings = {
    "thinking": bool(config.get("engine.thinking", False)),
    "effort": _normalize_effort(config.get("llm.reasoning", "high")),
}


def _apply_settings():
    if _engine is not None:
        _engine.set_thinking(_settings["thinking"], _settings["effort"])


def _start_engine():
    global _engine, _started
    with _lock:
        if _started:
            return
        _started = True

    _engine = Engine()

    # Engine 构造时按实例数据根重读了配置；页面设置跟着实例走
    _settings["thinking"] = bool(config.get("engine.thinking", False))
    _settings["effort"] = _normalize_effort(config.get("llm.reasoning", "high"))

    attach_output(_engine)   # 渲染出口
    attach_input(_engine)    # 输入源
    _engine.set_approver(               # 安全闸出口
        _approver,
        lambda: _deny_pending("已停止"),
    )
    _apply_settings()

    # 同步开机（BIOS + 恢复会话），保证页面第一次请求历史时已经就绪
    ok = _engine.start()

    def run():
        if ok:
            _engine.run()
        publish({"type": "engine_end"})

    threading.Thread(target=run, name="EngineThread", daemon=True).start()


def _settings_payload():
    workdir = config.get("engine.workdir", "") or str(Path.cwd())
    base = {
        "scenario": _engine.scenario if _engine is not None else str(
            config.get("engine.scenario", "daily")
        ),
        "approval": str(config.get("engine.approval", "ask")),
        "access": str(config.get("engine.access", "workspace")),
        "session_dir": _engine.session_dir if _engine is not None else "",
        "config_path": _engine.config_path if _engine is not None else "",
        "provider_id": str(config.get("llm.provider_id", "")),
        "workdir": workdir,
        "build": _engine.build if _engine is not None else os.environ.get("SPIRIT_BUILD", ""),
        "max_turn_tokens": int(config.get("engine.max_turn_tokens", 0) or 0),
        "max_session_tokens": int(config.get("engine.max_session_tokens", 0) or 0),
        "repeat_limit": int(config.get("engine.repeat_limit", 3) or 0),
        # 实际生效值：当前提供商填了就用它，否则回退全局 / 128000
        "context_window": Providers.active_value(config, "context_window", 128000),
        "sandbox_workspace": bool(config.get("engine.sandbox.workspace_only", True)),
        "auto_allow_outside": bool(config.get("engine.sandbox.auto_allow_outside", False)),
        "sandbox_paths": (
            _engine.sandbox_paths() if _engine is not None
            else [str(item) for item in (config.get("engine.sandbox.allow_paths", []) or [])]
        ),
        "untrusted_policy": str(config.get("engine.untrusted_policy", "confirm")),
        "failover": bool(config.get("engine.failover.enabled", False)),
    }
    if _engine is not None:
        data = _engine.settings()
        return {
            "thinking": data["thinking"],
            "effort": data["effort"],
            "model": data["model"],
            **base,
        }
    return {**_settings, "model": str(config.get("llm.model", "")), **base}


def _open_path(target):
    """只允许打开固定几样，避免变成任意文件打开器。"""
    if _engine is None:
        raise ValueError("引擎未启动")
    from Disk import disk

    targets = {
        "config": _engine.config_path,
        "sessions": _engine.session_dir,
        "workspace": _engine.workdir,
        "artifacts": str(disk.area("artifacts")),
        "sandbox": str(disk.area("sandbox")),
        "logs": str(disk.area("logs")),
        "uploads": str(disk.area("uploads")),
        "projects": str(disk.area("projects")),
    }
    path = targets.get(str(target))
    if not path:
        raise ValueError("未知目标")
    _open_with_system(path)
    return path


def _open_with_system(path):
    if not Path(path).exists():
        raise ValueError(f"路径不存在：{path}")
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — 桌面应用打开本地路径
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return path


def _open_project_file(session_id, name):
    """打开项目目录里的文件（默认项目总表 assets.csv）；只允许项目目录内。"""
    from Capabilities import Assets

    root = Assets.project_dir(session_id).resolve()
    target_name = Path(str(name or "").strip() or Assets.PROJECT_CSV).name
    path = (root / target_name).resolve()
    if path != root and root not in path.parents:
        raise ValueError("不在项目目录内")
    if not path.exists():
        raise ValueError(f"文件不存在：{target_name}")
    _open_with_system(path)
    return path


@app.route("/")
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    if not AUTH_DISABLED:
        tag = f'<meta name="spirit-api-token" content="{API_TOKEN}">'
        html = html.replace("<head>", "<head>\n  " + tag, 1)
    return Response(html, mimetype="text/html")


@app.route("/api/events")
def api_events():
    def stream():
        target = subscribe()
        try:
            while True:
                try:
                    event = target.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        finally:
            unsubscribe(target)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _request_runtime(data=None):
    sid = request.args.get("session") or (data or {}).get("session") or ""
    if _engine is None or not sid or sid == "primary":
        return None
    return _engine.runtime(sid)


@app.route("/api/history")
def api_history():
    """回放窗口：?limit=N 取最近 N 轮；?session= 指定额外会话。"""
    limit = request.args.get("limit", default=40, type=int) or 40
    if _engine is None:
        return {"events": [], "has_more": False, "limit": limit}
    runtime = _request_runtime()
    if runtime is not None:
        return runtime.history(limit)
    return _engine.history_window(limit)


@app.route("/api/sessions")
def api_sessions():
    """会话索引：新的在前；附带运行中的额外会话。"""
    if _engine is None:
        return []
    items = _engine.list_sessions()
    by_path = {}
    for item in items:
        # 只在磁盘上的会话还没开运行时；live 字段由下面覆盖
        item["session"] = None
        item["live"] = False
        item["running"] = False
        by_path[str(item.get("path") or "")] = item

    # 额外会话运行时（含还没落盘的“新会话”）
    for runtime in _engine.runtime_list():
        path = str(runtime.get("path") or "")
        item = by_path.get(path) if path else None
        if item is not None:
            item.update({
                "session": runtime["id"],
                "title": runtime.get("title") or item.get("title"),
                "running": bool(runtime.get("running")),
                "live": True,
                "mtime": runtime.get("mtime") or item.get("mtime"),
            })
        else:
            items.append({
                "path": path or None,
                "title": runtime.get("title") or "新会话",
                "records": int(runtime.get("records") or 0),
                "mtime": runtime.get("mtime") or 0,
                "scenario": "",
                "session": runtime["id"],
                "running": bool(runtime.get("running")),
                "live": True,
            })

    # 主会话：有记录 / 有文件 / 正在跑 才占位（纯空白的新会话不显示）
    primary = _engine.primary_info()
    path = str(primary.get("path") or "")
    if path and path in by_path:
        item = by_path[path]
        item.update({
            "session": "primary",
            "title": primary.get("title") or item.get("title"),
            "running": bool(primary.get("running")),
            "live": True,
            "mtime": max(item.get("mtime") or 0, primary.get("mtime") or 0),
        })
    elif primary.get("records") or primary.get("running") or path:
        items.append({
            "path": path or None,
            "title": primary.get("title") or "会话",
            "records": int(primary.get("records") or 0),
            "mtime": primary.get("mtime") or 0,
            "scenario": "",
            "session": "primary",
            "running": bool(primary.get("running")),
            "live": True,
        })

    items.sort(key=lambda entry: entry.get("mtime") or 0, reverse=True)
    return items


@app.route("/api/session", methods=["POST"])
def api_session():
    """切换会话：{path} 或 {new: true}。返回回放事件。"""
    data = request.get_json(silent=True) or {}
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    try:
        limit = max(1, min(int(data.get("limit") or 40), 500))
    except (TypeError, ValueError):
        limit = 40
    selected = str(data.get("session") or "")
    if selected and not data.get("new"):
        runtime = _engine.runtime(selected)
        if runtime is not None:
            window = runtime.history(limit)
            return {"ok": True, "session": runtime.id,
                    "title": runtime.display_title or "会话", **window,
                    "warnings": _engine.session_warnings()}
        if selected == "primary":
            window = _engine.history_window(limit)
            return {"ok": True, "session": "primary", "title": _engine.primary_title,
                    **window, "warnings": _engine.session_warnings()}

    if data.get("new"):
        from_other = str(data.get("session") or "primary") not in ("", "primary")
        if from_other:
            # 当前这条本来就是还没说话的空白会话：直接复用，别在侧栏堆“新会话”
            current = _engine.runtime(selected)
            if (
                current is not None
                and not current.current_path
                and not current.running
                and current.memory.last_seq() == 0
            ):
                return {"ok": True, "session": current.id, "title": "新会话",
                        "events": [], "has_more": False, "limit": limit,
                        "warnings": []}
        if _engine.primary_running or from_other:
            # 主会话还在跑：新开一条独立运行时，不打断它
            runtime = _engine.open_runtime()
            return {"ok": True, "session": runtime.id, "title": "新会话",
                    "events": [], "has_more": False, "limit": limit,
                    "warnings": []}
        try:
            _engine.new_session()
        except RuntimeError as error:
            return {"ok": False, "error": str(error)}, 409
        return {"ok": True, "session": "primary", "title": "新会话",
                "events": [], "has_more": False, "limit": limit, "warnings": []}

    path = data.get("path")
    if not path:
        return {"ok": False, "error": "no path"}, 400
    try:
        path = str(session_file(path))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400

    if path == _engine.primary_path:
        # 主会话正在跑也能切回来看：只取历史，不动它的运行状态
        window = _engine.history_window(limit)
        title = next(
            (item["title"] for item in _engine.list_sessions()
             if item["path"] == path),
            "会话",
        )
        return {"ok": True, "session": "primary", "title": title, **window,
                "warnings": _engine.session_warnings()}

    runtime = _engine.runtime_for_path(path)
    if runtime is None and path != _engine.primary_path and (
        _engine.primary_running or _engine.primary_path
    ):
        # 目标不是主会话：开独立运行时，主会话继续在后台跑
        runtime = _engine.open_runtime(path)
    if runtime is not None:
        window = runtime.history(limit)
        return {"ok": True, "session": runtime.id,
                "title": runtime.display_title or "会话", **window,
                "warnings": _engine.session_warnings()}

    try:
        window = _engine.load_session(path, limit_turns=limit)
    except RuntimeError as error:
        return {"ok": False, "error": str(error)}, 409
    except Exception as error:
        return {"ok": False, "error": str(error)}, 400
    title = next(
        (item["title"] for item in _engine.list_sessions() if item["path"] == path),
        "会话",
    )
    return {"ok": True, "session": "primary", "title": title, **window,
            "warnings": _engine.session_warnings()}


@app.route("/api/status")
def api_status():
    if _engine is None:
        return {"started": False, "running": False}
    return _engine.status()


@app.route("/api/running")
def api_running():
    if _engine is None:
        return {"calls": []}
    runtime = _request_runtime()
    if runtime is not None:
        return {"calls": _engine.running(runtime.id), "turn_active": runtime.running}
    return {"calls": _engine.running("primary")}


@app.route("/api/usage")
def api_usage():
    if _engine is None:
        return {"session": {}, "turn": {}, "last": None}
    runtime = _request_runtime()
    return runtime.usage() if runtime is not None else _engine.usage()


@app.route("/api/context")
def api_context():
    if _engine is None:
        return {"system": 0, "tools": 0, "messages": 0, "total": 0,
                "window": 0, "percent": 0}
    runtime = _request_runtime()
    return runtime.context() if runtime is not None else _engine.context()


@app.route("/api/interrupt", methods=["POST"])
def api_interrupt():
    data = request.get_json(silent=True) or {}
    runtime = _request_runtime(data)
    _deny_pending("已停止", (runtime.id if runtime is not None else "primary"))
    if runtime is not None:
        runtime.cpu.interrupt()
    elif _engine is not None:
        _engine.interrupt()
    return {"ok": True}


@app.route("/api/approval", methods=["POST"])
def api_approval():
    """用户对一个审批请求的答复：{id, allow}。"""
    data = request.get_json(silent=True) or {}
    request_id = data.get("id")
    allow = bool(data.get("allow"))
    remember = bool(data.get("remember"))
    if not request_id:
        return {"ok": False, "error": "id required"}, 400

    with _pending_lock:
        item = _pending.pop(request_id, None)
    if item is None:
        return {"ok": False, "error": "请求已失效"}, 404

    answer, _request = item
    try:
        answer.put_nowait({"allow": allow, "remember": remember})
    except queue.Full:
        return {"ok": False, "error": "请求已处理"}, 409

    publish({
        "type": "approval_resolved",
        "id": request_id,
        "allow": allow,
        "reason": "用户允许" if allow else "用户拒绝",
    })
    return {"ok": True, "allow": allow}


@app.route("/api/session/rename", methods=["POST"])
def api_rename():
    data = request.get_json(silent=True) or {}
    path = data.get("path")
    title = (data.get("title") or "").strip()
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    if not path or not title:
        return {"ok": False, "error": "path/title required"}, 400
    try:
        path = str(session_file(path))
        _engine.rename_session(path, title)
    except Exception as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "title": title}


@app.route("/api/session/delete", methods=["POST"])
def api_delete():
    data = request.get_json(silent=True) or {}
    path = data.get("path")
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    if not path:
        return {"ok": False, "error": "path required"}, 400
    try:
        path = str(session_file(path))
        runtime = _engine.runtime_for_path(path)
        if runtime is not None and runtime.running:
            return {"ok": False, "error": "这个会话还在跑，先停止再删除"}, 409
        deleted = _engine.delete_session(path)
    except RuntimeError as error:
        return {"ok": False, "error": str(error)}, 409
    except Exception as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "deleted": bool(deleted)}


@app.route("/api/settings", methods=["GET"])
def get_settings():
    return _settings_payload()


@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.get_json(silent=True) or {}
    if "thinking" in data:
        _settings["thinking"] = bool(data["thinking"])
        config.set("engine.thinking", _settings["thinking"])   # 两处界面都读这一份，重启也在
        config.save()
    if "effort" in data:
        effort = _normalize_effort(data["effort"], default="")
        if not effort:
            return {"ok": False, "error": "invalid effort"}, 400
        _settings["effort"] = effort
        config.set("llm.reasoning", effort)
        config.save()

    limits = {}
    for key in ("max_turn_tokens", "max_session_tokens", "repeat_limit"):
        if key in data:
            try:
                limits[key] = max(0, int(data[key]))
            except (TypeError, ValueError):
                return {"ok": False, "error": f"{key} 需要非负整数"}, 400
    if limits:
        for key, value in limits.items():
            config.set(f"engine.{key}", value)
        config.save()

    if "context_window" in data:
        try:
            window = int(data["context_window"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "context_window 需要整数"}, 400
        if window < 1000 or window > 10_000_000:
            return {"ok": False, "error": "context_window 需要在 1000–10000000 之间"}, 400
        config.set("llm.context_window", window)
        config.save()

    if "sandbox_workspace" in data:
        config.set("engine.sandbox.workspace_only", bool(data["sandbox_workspace"]))
        config.save()
        if _engine is not None:
            _engine.reload_sandbox()

    if "auto_allow_outside" in data:
        config.set(
            "engine.sandbox.auto_allow_outside",
            bool(data["auto_allow_outside"]),
        )
        config.save()

    if "untrusted_policy" in data:
        policy = str(data["untrusted_policy"]).lower()
        if policy not in {"warn", "confirm", "block"}:
            return {"ok": False, "error": "invalid untrusted_policy"}, 400
        config.set("engine.untrusted_policy", policy)
        config.save()

    if "failover" in data:
        config.set("engine.failover.enabled", bool(data["failover"]))
        config.save()

    _apply_settings()
    return {"ok": True, **_settings_payload()}


@app.route("/api/scenarios", methods=["GET"])
def api_scenarios():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    return {"ok": True, **_engine.scenarios(request.args.get("session"))}


@app.route("/api/scenario", methods=["POST"])
def api_scenario():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    session = str(data.get("session") or "")
    if session and session != "primary":
        runtime = _engine.runtime(session)
        if runtime is None:
            return {"ok": False, "error": "会话不存在"}, 404
        try:
            item = runtime.set_scenario(data.get("id"))
        except RuntimeError as error:
            return {"ok": False, "error": str(error)}, 409
        except ValueError as error:
            return {"ok": False, "error": str(error)}, 400
        # 额外会话只切自己的场景；审批 / 沙箱等全局默认值不动
        return {"ok": True, "current": item["id"], "scenario": item,
                "capabilities": None, "settings": None}
    try:
        result = _engine.use_scenario(data.get("id"))
    except RuntimeError as error:
        return {"ok": False, "error": str(error)}, 409
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/scope")
def api_get_scope():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    return {"ok": True, "scope": _engine.pentest_scope()}


@app.route("/api/scope", methods=["POST"])
def api_set_scope():
    """渗透授权范围：{scope: [目标...]}（也接受 {text: "一行一个"}）。"""
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    items = data.get("scope")
    if items is None:
        items = data.get("text") or ""
    try:
        scope = _engine.set_pentest_scope(items)
    except RuntimeError as error:
        return {"ok": False, "error": str(error)}, 409
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "scope": scope}


@app.route("/api/open", methods=["POST"])
def api_open():
    data = request.get_json(silent=True) or {}
    try:
        path = _open_path(data.get("target"))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "path": path}


@app.route("/api/kernel", methods=["GET"])
def api_kernel():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    runtime = _request_runtime()
    if runtime is not None:
        from Capabilities import Browser, capabilities
        from DC.Reconnect import reconnect
        return {
            "ok": True,
            "cpu": {"state": runtime.cpu.state, "turn_active": runtime.running},
            "queued": runtime.queue_size,
            "session": runtime.id,
            "running": len(capabilities.running(runtime.id)),
            "browser": Browser.health(),
            "retry": reconnect.snapshot(),
        }
    session_id = request.args.get("session") or "primary"
    return {
        "ok": True,
        **( _engine.kernel_stats(session_id)),
        "queued": inputs.qsize(),
    }


@app.route("/api/browser", methods=["GET"])
def api_browser():
    """浏览器外设状态：安装 / 应用 / onboarding / 当前 Space / 最近截图。"""
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Browser

    session_id = request.args.get("session") or "primary"
    return {"ok": True, **Browser.status(session_id)}


@app.route("/api/browser/shot", methods=["GET"])
def api_browser_shot():
    """最近一张浏览器截图（只允许上传区里的标准文件名）。"""
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 404
    from Capabilities import Browser

    session_id = request.args.get("session") or "primary"
    last = Browser.last_screenshot(session_id) or {}
    name = str(last.get("upload") or "")
    if not re.fullmatch(r"[0-9a-f]{32}\.(?:png|jpg|jpeg|webp|gif)", name):
        return {"ok": False, "error": "没有截图"}, 404
    directory = str(disk.area("uploads"))
    if not (Path(directory) / name).exists():
        return {"ok": False, "error": "截图不在了"}, 404
    return send_from_directory(directory, name, max_age=0)


@app.route("/api/assets", methods=["GET"])
def api_assets():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    session_id = request.args.get("session") or "primary"
    try:
        limit = max(1, min(1000, int(request.args.get("limit") or 500)))
    except (TypeError, ValueError):
        limit = 500
    return {
        "ok": True,
        "session": session_id,
        "summary": Assets.summary(session_id),
        "assets": Assets.list_assets(
            session_id, limit=limit,
            kind=request.args.get("kind") or "",
            search=request.args.get("search") or "",
        ),
        "queries": Assets.queries(session_id, 100),
    }


@app.route("/api/assets/projects", methods=["GET"])
def api_asset_projects():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    current = request.args.get("session") or "primary"
    Assets.project_dir(current)   # 保证当前项目在列表里
    return {"ok": True, "current": current, "projects": Assets.projects()}




@app.route("/api/assets/csv/import", methods=["POST"])
def api_assets_csv_import():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    data = request.get_json(silent=True) or {}
    try:
        name = Assets.import_csv(
            str(data.get("session") or "primary"),
            data.get("name") or "upload.csv",
            data.get("text") or "",
        )
    except Exception as error:
        return {"ok": False, "error": str(error)}, 400
    return {
        "ok": True, "name": name,
        "hint": f"已导入 {name}。在对话里让 Spirit 读出来、整理进项目总表（assetsWrite）。",
    }


def _nuclei_templates_ready():
    """只判断模板目录是否存在——递归数 1.3 万个 yaml 会让信息收集页首开卡几秒。"""
    try:
        from Capabilities.Nuclei import DEFAULT_TEMPLATES
        return Path(DEFAULT_TEMPLATES).is_dir()
    except OSError:
        return False


@app.route("/api/assets/collect-tools", methods=["GET"])
def api_assets_collect_tools():
    """信息收集页的工具状态：subfinder / crt.sh / dnsx / 字典 / nuclei / gau。"""
    from Capabilities.DomainCollect import wordlist_info
    from Capabilities.Tools import tool_path

    subfinder = tool_path("subfinder")
    dnsx = tool_path("dnsx")
    nuclei = tool_path("nuclei")
    gau = tool_path("gau")
    wordlist = wordlist_info()
    templates_ready = _nuclei_templates_ready()
    tools = [
        {"name": "subfinder", "ok": subfinder is not None,
         "detail": "被动多源 · 已安装" if subfinder else "未安装（配置 tools.subfinder）"},
        {"name": "crt.sh", "ok": True, "detail": "证书透明度 · 联网查询"},
        {"name": "dnsx", "ok": dnsx is not None,
         "detail": "主动爆破 + 解析 · 已安装" if dnsx else "未安装（配置 tools.dnsx）"},
        {"name": "子域字典", "ok": wordlist["exists"],
         "detail": f"{wordlist['rows']} 条" if wordlist["exists"] else "缺失"},
        {"name": "nuclei", "ok": nuclei is not None and templates_ready,
         "detail": "模板已安装" if nuclei and templates_ready else "未安装 / 模板缺失"},
        {"name": "gau", "ok": gau is not None,
         "detail": "历史 URL · 已安装" if gau else "未安装（配置 tools.gau）"},
    ]
    return {"ok": True, "tools": tools}


@app.route("/api/assets/csv/open", methods=["POST"])
def api_assets_csv_open():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        path = _open_project_file(str(data.get("session") or "primary"), data.get("name"))
    except Exception as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "path": str(path)}

@app.route("/api/assets/csvs", methods=["GET"])
def api_assets_csvs():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    session_id = request.args.get("session") or "primary"
    return {"ok": True, "files": Assets.list_csv(session_id)}


@app.route("/api/assets/csv/view", methods=["GET"])
def api_assets_csv_view():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    session_id = request.args.get("session") or "primary"
    try:
        data = Assets.read_csv(session_id, request.args.get("name"), request.args.get("limit") or 200)
    except Exception as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **data}

@app.route("/api/assets/csv", methods=["GET"])
def api_assets_csv():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    session_id = request.args.get("session") or "primary"
    kind = request.args.get("kind") or ""
    text = Assets.csv_text(session_id, kind)
    name = f"assets-{kind or 'all'}.csv"
    return Response(
        "﻿" + text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.route("/api/assets/clear", methods=["POST"])
def api_assets_clear():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import Assets

    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session") or "primary")
    return {"ok": True, "removed": Assets.clear(session_id)}


@app.route("/api/assets/platforms", methods=["GET"])
def api_asset_platforms():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import AssetPlatforms

    return {"ok": True, "platforms": AssetPlatforms.platforms()}


@app.route("/api/assets/platforms", methods=["POST"])
def api_asset_platform_save():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import AssetPlatforms

    data = request.get_json(silent=True) or {}
    platform = str(data.get("platform") or "").strip()
    try:
        state = AssetPlatforms.save_platform(
            platform,
            enabled=data.get("enabled"),
            key=data.get("key"),
            base_url=data.get("base_url"),
        )
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "platform": state}


@app.route("/api/assets/platform/test", methods=["POST"])
def api_asset_platform_test():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    from Capabilities import AssetPlatforms

    data = request.get_json(silent=True) or {}
    platform = str(data.get("platform") or "").strip()
    try:
        state = AssetPlatforms.probe(platform)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "status": state}


@app.route("/api/disk", methods=["GET"])
def api_disk():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    return {"ok": True, **_engine.disk_info()}


@app.route("/api/disk/clear", methods=["POST"])
def api_disk_clear():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        removed = _engine.disk_clear(data.get("area") or "artifacts")
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "removed": removed, **_engine.disk_info()}


@app.route("/api/providers", methods=["GET"])
def api_providers():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    return _engine.providers()


@app.route("/api/provider", methods=["POST"])
def api_provider_save():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        item = _engine.save_provider(data)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "provider": item, **_engine.providers()}


@app.route("/api/provider", methods=["DELETE"])
def api_provider_delete():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.delete_provider(str(data.get("id") or ""))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/provider/models", methods=["POST"])
def api_provider_models():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        models = _engine.probe_models(data)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "models": models}


@app.route("/api/provider/duplicate", methods=["POST"])
def api_provider_duplicate():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.duplicate_provider(str(data.get("id") or ""))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/provider/reorder", methods=["POST"])
def api_provider_reorder():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.reorder_providers(data.get("ids") or [])
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/provider/check", methods=["POST"])
def api_provider_check():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.check_provider(data)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/provider/speedtest", methods=["POST"])
def api_provider_speedtest():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.speed_test(data)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/provider/balance", methods=["POST"])
def api_provider_balance():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.query_balance(data)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/providers/export", methods=["POST"])
def api_providers_export():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return {"ok": False, "error": "导出包含明文 Key，需要显式确认（confirm=true）"}, 400
    return {"ok": True, **_engine.export_providers()}


@app.route("/api/providers/import", methods=["POST"])
def api_providers_import():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.import_providers(data)
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/provider/active", methods=["POST"])
def api_provider_active():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.activate_provider(
            str(data.get("id") or ""), data.get("model")
        )
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {
        "ok": bool(result.get("reloaded")),
        **result,
        "settings": _settings_payload(),
    }


@app.route("/api/sandbox/paths", methods=["POST"])
def api_sandbox_paths():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        paths = _engine.set_sandbox_paths(data.get("paths") or [])
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "sandbox_paths": paths, "settings": _settings_payload()}


@app.route("/api/access-mode", methods=["POST"])
def api_access_mode():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        access = _engine.set_access(data.get("access"))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "access": access}


@app.route("/api/approval-mode", methods=["POST"])
def api_approval_mode():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        mode = _engine.set_approval(data.get("mode"))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, "approval": mode}


@app.route("/api/workspaces", methods=["GET"])
def api_workspaces():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    return {"ok": True, **_engine.workspaces()}


@app.route("/api/workspace", methods=["POST"])
def api_workspace_add():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.add_workspace(str(data.get("path") or ""), data.get("name"))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result}


@app.route("/api/workspace/select", methods=["POST"])
def api_workspace_select():
    if _engine is None:
        return {"ok": False, "error": "engine not started"}, 400
    data = request.get_json(silent=True) or {}
    try:
        result = _engine.select_workspace(str(data.get("path") or ""))
    except ValueError as error:
        return {"ok": False, "error": str(error)}, 400
    return {"ok": True, **result, "settings": _settings_payload()}


UPLOAD_RE = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|jpeg|webp|gif)$")
UPLOAD_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
}
UPLOAD_MAX = 8 * 1024 * 1024
UPLOAD_COUNT = 4


def _upload_dir():
    return disk.area("uploads")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """接收 data URL（浏览器 FileReader 的产物），落盘返回 id。"""
    data = request.get_json(silent=True) or {}
    raw = str(data.get("data") or "")
    if not raw:
        return {"ok": False, "error": "data required"}, 400
    if raw.startswith("data:"):
        try:
            header, raw = raw.split(",", 1)
            mime = header[5:].split(";", 1)[0].strip().lower()
        except ValueError:
            return {"ok": False, "error": "bad data url"}, 400
    else:
        mime = str(data.get("mime") or "image/png").lower()
    if not mime.startswith("image/"):
        return {"ok": False, "error": "只支持图片"}, 400
    ext = {"image/png": "png", "image/jpeg": "jpeg", "image/jpg": "jpeg",
           "image/webp": "webp", "image/gif": "gif"}.get(mime)
    if not ext:
        return {"ok": False, "error": f"不支持的图片类型：{mime}"}, 400
    try:
        blob = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "error": "图片数据不是合法 base64"}, 400
    if len(blob) > UPLOAD_MAX:
        return {"ok": False, "error": "图片太大（上限 8MB）"}, 400
    name = f"{uuid.uuid4().hex}.{ext}"
    target = _upload_dir() / name
    temp = target.with_name(f".{name}.{uuid.uuid4().hex}.tmp")
    temp.write_bytes(blob)
    os.replace(temp, target)
    return {"ok": True, "id": name, "mime": mime, "url": f"/api/upload/{name}"}


@app.route("/api/upload/<name>", methods=["GET"])
def api_upload_get(name):
    if not UPLOAD_RE.match(str(name)):
        return {"ok": False, "error": "not found"}, 404
    return send_from_directory(str(_upload_dir()), name)


@app.route("/api/send", methods=["POST"])
def send():
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()
    names = data.get("images") or []
    if not isinstance(names, list) or len(names) > UPLOAD_COUNT:
        return {"ok": False, "error": f"图片最多 {UPLOAD_COUNT} 张"}, 400
    images = []
    for name in names:
        name = str(name or "")
        if not UPLOAD_RE.match(name) or not (_upload_dir() / name).exists():
            return {"ok": False, "error": "图片不存在或已失效"}, 400
        ext = name.rsplit(".", 1)[-1].lower()
        images.append({"id": name, "mime": UPLOAD_MIME.get(ext, "image/png")})
    if not text and not images:
        return {"ok": False, "error": "empty"}, 400
    sid = str(data.get("session") or "")
    if sid and sid != "primary" and _engine is not None and _engine.runtime(sid) is None:
        return {"ok": False, "error": "会话不存在（可能已关闭或删除）"}, 404
    runtime = _request_runtime(data)
    if runtime is not None:
        runtime.send(text, images)
    else:
        inputs.put({"text": text, "images": images} if images else text)
    return {"ok": True, "images": len(images), "session": runtime.id if runtime else "primary"}


@app.route("/api/stop", methods=["POST"])
def stop():
    _deny_pending("引擎停止")
    inputs.put(None)
    if _engine is not None:
        _engine.stop()
    return {"ok": True}


def main():
    from MoBo.lock import acquire_for_current_home
    try:
        acquire_for_current_home()
    except RuntimeError as error:
        print(f"[Spirit] {error}", file=sys.stderr)
        raise SystemExit(2)
    _start_engine()
    # 桌面壳用环境变量指定端口 / 地址（不改用户配置）
    host = os.environ.get("SPIRIT_WEB_HOST") or config.get("engine.web_host", "127.0.0.1")
    port = int(os.environ.get("SPIRIT_WEB_PORT") or config.get("engine.web_port", 5000))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
