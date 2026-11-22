"""
能力体系：Agent 通用计算机的能力容器（主体系）

职责：
  1. 注册表：所有能力的加载 / 启停 / 注销都走 Capabilities/Registry
  2. 执行：按 CPU 的调度跑能力（线程池，按提交顺序收）
  3. 后处理：校验 / 截断 / spill 落盘
  4. 把结果写进数据表 tool_output（GPU 从那里读）

与模型之间的三个契约：
  说明：spec() → registry.schemas() → ModI → 请求的 tools 字段
  输入：模型 function_call → ModO 写 tool_call → CPU 读表 → CapabilityInput
  返回：run() 的返回值 → CapabilityOutput → 截断/spill → 写 tool_output
"""
import json
import os
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

from Cancel import token as cancel_token
from Config import config
from Faults import faults
from Log import log
from Memory import mem, TODO, TOOL_OUTPUT, STREAM
from Disk import disk
from Paths import spill_dir

from Redact import redact

from .Executions import ExecutionCancelled, executions
from .WorkerPool import WORKER_NAMES, WorkerPool
from .Input import CapabilityInput
from .Output import CapabilityOutput, CapabilityResult
from .Registry import Registry, RegistryError
from .Sandbox import SandboxDenied, sandbox
from .Validate import validate_arguments

# 会话级能力白名单：额外会话在自己的线程里绑定 scope，按场景过滤
# 模型看到的 tools 和实际能执行的能力；主会话不绑（走全局 registry 启停）。
_SCOPE = contextvars.ContextVar("spirit_capability_scope", default=None)


class CapabilityScope:
    """可变的会话能力白名单：服务线程改 names，CPU 线程直接读到新值。"""

    def __init__(self, names=None):
        self.names = frozenset(str(name) for name in (names or ()))

    def allows(self, name):
        return str(name or "") in self.names

    def set(self, names):
        self.names = frozenset(str(name) for name in (names or ()))

    def token(self):
        return tuple(sorted(self.names))


def current_scope():
    return _SCOPE.get()


def use_scope(scope):
    return _SCOPE.set(scope)


def unuse_scope(token):
    _SCOPE.reset(token)

# 内置能力：同样走注册表加载
BUILTIN = [
    {"module": "Capabilities.Bash", "class": "BashCapability"},
    {"module": "Capabilities.ReadFile", "class": "ReadFileCapability"},
    {"module": "Capabilities.ViewImage", "class": "ViewImageCapability"},
    {"module": "Capabilities.WriteFile", "class": "WriteFileCapability"},
    {"module": "Capabilities.ListDir", "class": "ListDirCapability"},
    {"module": "Capabilities.ReplaceInFile", "class": "ReplaceInFileCapability"},
    {"module": "Capabilities.SearchFiles", "class": "SearchFilesCapability"},
    {"module": "Capabilities.FindFiles", "class": "FindFilesCapability"},
    {"module": "Capabilities.FetchUrl", "class": "FetchUrlCapability"},
    {"module": "Capabilities.WebSearch", "class": "WebSearchCapability"},
    {"module": "Capabilities.Browser", "class": "BrowserCapability"},
    {"module": "Capabilities.AssetPlatforms", "class": "FofaSearchCapability"},
    {"module": "Capabilities.AssetPlatforms", "class": "QuakeSearchCapability"},
    {"module": "Capabilities.AssetPlatforms", "class": "HunterSearchCapability"},
    {"module": "Capabilities.Recon", "class": "SubfinderCapability"},
    {"module": "Capabilities.Recon", "class": "FfufCapability"},
    {"module": "Capabilities.Recon", "class": "NaabuCapability"},
    {"module": "Capabilities.ProjectAssets", "class": "AssetsWriteCapability"},
    {"module": "Capabilities.DomainCollect", "class": "CrtShCapability"},
    {"module": "Capabilities.DomainCollect", "class": "SubdomainBruteCapability"},
    {"module": "Capabilities.DomainCollect", "class": "DomainCollectCapability"},
    {"module": "Capabilities.Nuclei", "class": "NucleiScanCapability"},
    {"module": "Capabilities.Nuclei", "class": "GauUrlsCapability"},
    {"module": "Capabilities.ProcessStart", "class": "ProcessStartCapability"},
    {"module": "Capabilities.ProcessList", "class": "ProcessListCapability"},
    {"module": "Capabilities.ProcessOutput", "class": "ProcessOutputCapability"},
    {"module": "Capabilities.ProcessKill", "class": "ProcessKillCapability"},
    {"module": "Capabilities.Todo", "class": "TodoWriteCapability"},
    {"module": "Capabilities.Todo", "class": "TodoReadCapability"},
    {"module": "Capabilities.SessionQuery", "class": "SessionSearchCapability"},
    {"module": "Capabilities.IsolatedRun", "class": "IsolatedRunCapability"},
    {"module": "Capabilities.InfoGather", "class": "DnsLookupCapability"},
    {"module": "Capabilities.InfoGather", "class": "PortScanCapability"},
    {"module": "Capabilities.InfoGather", "class": "HttpProbeCapability"},
    {"module": "Capabilities.HttpRequest", "class": "HttpRequestCapability"},
    {"module": "Capabilities.DataParse", "class": "DataParseCapability"},
    {"module": "Capabilities.Archive", "class": "ArchiveListCapability"},
    {"module": "Capabilities.Archive", "class": "ArchiveExtractCapability"},
    {"module": "Capabilities.Archive", "class": "ArchiveCreateCapability"},
]


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class _TodoStore:
    """内核给 todo 能力的存储口：插件不直接碰数据表。"""

    def save(self, items):
        mem.submit(TODO, {"items": items})

    def load(self):
        mem.flush()
        records = mem.view(TODO)
        if not records:
            return []
        payload = records[-1].payload
        if not isinstance(payload, dict):
            return []
        return list(payload.get("items") or [])


class CapabilitySystem:
    def __init__(self):
        self.__faults = faults.for_system("Capabilities")
        self.__handlers = {}   # 每个能力一个异常 handler（按名字复用）
        self.__default_timeout = _safe_float(config.get("engine.capability_timeout", 60), 60.0)
        self.__workers = max(1, _safe_int(config.get("engine.tool_workers", 4), 4))
        self.__pool = ThreadPoolExecutor(max_workers=self.__workers)
        self.__pool_losses = 0
        self.__inline = _safe_int(config.get("engine.tool_output_inline", 4000), 4000)
        self.__active = 0
        self.__active_lock = threading.Lock()
        self.__counters = {"calls": 0, "failures": 0}
        self.__counters_lock = threading.Lock()

        self.__env = {
            "workdir": config.get("engine.workdir", "") or os.getcwd(),
            "config": config,
            "log": log,
            "faults": faults,
            "sandbox": sandbox,
            "disk": disk,
            "todo": _TodoStore(),
        }
        self.__worker_pool = None
        self.registry = Registry(self.__env)
        for entry in BUILTIN:
            try:
                self.registry.load(entry)
            except Exception as error:
                self.__faults.report(error, f"load:{entry.get('class', '')}")

    def rebind(self):
        """重新读配置 / 工作目录（Engine 构造时调；数据根和工作区由实例决定）。"""
        sandbox.reload()
        self.__default_timeout = _safe_float(config.get("engine.capability_timeout", 60), 60.0)
        self.__inline = _safe_int(config.get("engine.tool_output_inline", 4000), 4000)

        workers = max(1, _safe_int(config.get("engine.tool_workers", 4), 4))
        if workers != self.__workers:
            self.__workers = workers
            if self.__pool is not None:
                self.__pool.shutdown(wait=False)
                self.__pool = None

        self.__env["workdir"] = config.get("engine.workdir", "") or os.getcwd()
        self.registry.rebind(self.__env)

    # ---------- 注册表入口 ----------
    def register(self, capability, config=None):
        """登记一个能力（对象形式）。"""
        return self.registry.add(capability, config=config)

    def unregister(self, name):
        return self.registry.remove(name)

    def enable(self, name):
        return self.registry.enable(name)

    def disable(self, name):
        return self.registry.disable(name)

    def load_manifest(self, path):
        """从 JSON 清单加载：{"capabilities": [{"module", "class", "config"}]}"""
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
        loaded = []
        for entry in data.get("capabilities", []):
            try:
                loaded.append(self.registry.load(entry).name)
            except (RegistryError, ImportError, AttributeError) as error:
                self.__faults.report_message(str(error), "manifest")
        return loaded

    @staticmethod
    def __entry_available(entry):
        check = getattr(entry.capability, "available", None)
        if not callable(check):
            return True
        try:
            return bool(check())
        except Exception:
            return False

    def schemas(self):
        """给大模型的说明清单。

        主会话：全局启停（场景通过 apply_scenario 整体启停）。
        额外会话：按自己的 scope 过滤；全局启停是主会话的场景，不参与。
        外部工具（FOFA / ffuf / subfinder…）没配置/没安装时不出现。
        """
        scope = _SCOPE.get()
        result = []
        for entry in self.registry.list():
            if scope is not None:
                if not scope.allows(entry.name):
                    continue
            elif not entry.enabled:
                continue
            if not self.__entry_available(entry):
                continue
            result.append({
                "type": "function",
                "name": entry.spec.name,
                "description": entry.spec.description,
                "parameters": entry.spec.parameters,
            })
        return result

    def version(self):
        """工具定义版本：GPU 用它决定要不要重新估算 schema 的 token 基数。"""
        scope = _SCOPE.get()
        names = tuple(
            entry.name for entry in self.registry.list()
            if self.__entry_available(entry)
        )
        if scope is None:
            return (self.registry.version(), names)
        return (self.registry.version(), scope.token(), names)

    # ---------- 执行（CPU 调度入口） ----------
    def side_effect(self, name):
        """能力的副作用声明：read / write / external；未知能力按 write 保守处理。"""
        entry = self.registry.get(name)
        if entry is None:
            return "write"
        return getattr(entry.spec, "side_effect", "write")

    def run(self, inputs):
        self.__ensure_pool()
        # 批内有写：整批串行（保守但正确）；全只读 / external 才并行
        if any(self.side_effect(item.name) == "write" for item in inputs):
            return self.__run_serial(inputs)
        return self.__run_parallel(inputs)

    def __run_parallel(self, inputs):
        running = []
        failed = []
        for item in inputs:
            try:
                future, execution = self.__start(item)
            except Exception as error:
                # 调度失败（例如执行池重建瞬间 submit 被拒）：不能中断整批，
                # 也不能把已经 start 的条目丢在 __finish 外面（__active 会只增不减）
                log.error("Capabilities", f"schedule failed {item.name}: {error}")
                output = CapabilityOutput(
                    item.call_id, f"能力调度失败：{error}", ok=False
                )
                mem.submit(TOOL_OUTPUT, output.to_record())
                failed.append(output)
                continue
            running.append((item, future, execution))
        outputs = failed + [self.__finish(*entry) for entry in running]
        return outputs

    def __run_serial(self, inputs):
        outputs = []
        for item in inputs:
            if cancel_token.is_set():
                output = CapabilityOutput(
                    item.call_id, "已取消：用户停止", ok=False
                )
                log.info("Capabilities", f"result {item.name} ok=False cancelled")
                mem.submit(TOOL_OUTPUT, output.to_record())
                outputs.append(output)
                continue
            future, execution = self.__start(item)
            outputs.append(self.__finish(item, future, execution))
        return outputs

    def __queue_limit(self):
        return max(1, _safe_int(config.get("engine.capability_queue", 32), 32))

    def __output_sink(self, item):
        """能力执行中的输出片段 → 瞬态表（渲染发 tool_delta）；和最终结果同样脱敏。"""
        def sink(text):
            if not text:
                return
            mem.push_transient(STREAM, {
                "tool": True,
                "call_id": item.call_id,
                "delta": redact(str(text), extra=[config.get("llm.api_key", "")]),
            })
        return sink

    def __start(self, item):
        log.info(
            "Capabilities",
            f"call {item.name} "
            + redact(item.raw_arguments[:120], extra=[config.get("llm.api_key", "")]),
        )
        limit = self.__queue_limit()
        with self.__active_lock:
            if self.__active >= limit:
                overloaded = True
            else:
                self.__active += 1
                overloaded = False
        if overloaded:
            return None, None
        try:
            execution = executions.create(
                item.call_id,
                item.name,
                self.__timeout_of(item.name),
                sink=self.__output_sink(item),
            )
            context = contextvars.copy_context()
            future = self.__pool.submit(context.run, self.__execute_bound, item, execution)
        except Exception:
            with self.__active_lock:
                self.__active = max(0, self.__active - 1)
            raise
        return future, execution

    def __finish(self, item, future, execution):
        if future is None:
            output = CapabilityOutput(
                item.call_id,
                f"能力队列已满（上限 {self.__queue_limit()}），这次调用没有执行；"
                "缩小批次或稍后重试",
                ok=False,
            )
            log.warning("Capabilities", f"overloaded: {item.name} rejected")
            mem.submit(TOOL_OUTPUT, output.to_record())
            return output
        handler = self.__handler(item.name)
        output = self.__wait(item, future, execution, handler)
        executions.finish(
            item.call_id, "done" if output.ok else "error", execution.reason
        )

        try:
            output = self.__postprocess(item, output)
        except Exception as error:
            handler.report(error, "postprocess")
            output = CapabilityOutput(item.call_id, f"结果处理失败：{error}", ok=False)

        # 统一的失败标记：模型不必猜“空输出 / 中文提示”算不算失败
        if not output.ok and not output.content.startswith("失败："):
            output = CapabilityOutput(
                output.call_id, f"失败：{output.content}", ok=False, meta=output.meta,
            )

        log.info("Capabilities", f"result {item.name} ok={output.ok} {len(output.content)} chars")
        with self.__active_lock:
            self.__active = max(0, self.__active - 1)
        with self.__counters_lock:
            self.__counters["calls"] += 1
            if not output.ok:
                self.__counters["failures"] += 1
        mem.submit(TOOL_OUTPUT, output.to_record())  # 数据到表，GPU 会读
        return output

    def __execute_bound(self, item, execution):
        """线程池里真正跑能力：先把这个调用绑到当前线程。"""
        executions.bind(execution)
        try:
            return self.__execute(item)
        except SandboxDenied as error:
            return CapabilityOutput(item.call_id, f"沙箱拒绝：{error}", ok=False)
        except ExecutionCancelled as error:
            return CapabilityOutput(item.call_id, f"已取消：{error}", ok=False)
        finally:
            executions.bind(None)

    def __pool_recover(self):
        """超时 / 取消的线程杀不掉：换一个执行池，别让 4 个僵尸把后续调用永久堵死。"""
        old = self.__pool
        if old is None:
            return
        self.__pool_losses += 1
        self.__pool = ThreadPoolExecutor(max_workers=self.__workers)
        old.shutdown(wait=False)   # 不取消排队任务：同批其它调用还要用这个池
        log.warning(
            "Capabilities",
            f"执行池重建（第 {self.__pool_losses} 次）：有线程超时/取消后没有退出",
        )

    def __wait(self, item, future, execution, handler):
        """等结果，但每 0.2 秒看一眼取消 / 超时；不再死等整个 timeout。"""
        while True:
            try:
                return future.result(timeout=0.2)
            except FutureTimeout:
                pass
            except Exception as error:
                handler.report(error, "run")
                return CapabilityOutput(
                    item.call_id, f"能力执行异常：{error}", ok=False
                )

            if execution.cancel.is_set():
                executions.cancel(item.call_id, execution.reason or "用户停止")
                future.cancel()
                self.__pool_recover()
                return CapabilityOutput(
                    item.call_id,
                    f"已取消：{execution.reason or '用户停止'}",
                    ok=False,
                )

            if time.monotonic() >= execution.deadline:
                executions.cancel(item.call_id, "超时")
                future.cancel()
                self.__pool_recover()
                message = (
                    f"能力超时：超过 {execution.timeout:g} 秒没有返回（已请求终止）"
                )
                handler.report_message(message, "timeout")
                return CapabilityOutput(item.call_id, message, ok=False)

    # ---------- 执行子体系（给 CPU / 前端看） ----------
    def running(self, session_id=None):
        return executions.snapshot(session_id)

    def cancel_all(self, reason="用户停止", session_id=None):
        return executions.cancel_all(reason, session_id=session_id)

    # ---------- 场景（能力子集） ----------
    def apply_scenario(self, names):
        """按场景白名单启停能力；不注销、不 dispose。"""
        return self.registry.set_enabled(names or [])

    # ---------- 沙箱（给 CPU 预检 / 设置切换） ----------
    def grant_once(self, path):
        return sandbox.grant_once(path)

    def grant_session(self, path):
        return sandbox.grant_session(path)

    def clear_once(self):
        sandbox.clear_once()

    def last_denial(self):
        return dict(getattr(sandbox, "last_denial", {}) or {})

    def precheck(self, name, arguments):
        return sandbox.precheck(name, arguments)

    def reload_sandbox(self):
        sandbox.reload()
        return True

    def __handler(self, name):
        """每个能力一个异常 handler：异常记录里能看出是谁。"""
        if name not in self.__handlers:
            self.__handlers[name] = faults.for_system(f"capability:{name}")
        return self.__handlers[name]

    def __timeout_of(self, name):
        """本次调用最多等多久：能力自己声明的优先，否则用全局默认。"""
        entry = self.registry.get(name)
        if entry is not None and entry.spec.timeout:
            return float(entry.spec.timeout)
        return self.__default_timeout

    def stats(self):
        """内核能力层健康：队列 / 失败数 / worker 池。给 /api/kernel 和故障排查用。"""
        with self.__counters_lock:
            counters = dict(self.__counters)
        with self.__active_lock:
            active = self.__active
        pool = self.__worker_pool.stats() if self.__worker_pool is not None else {
            "enabled": False, "workers": 0, "busy": 0, "pids": []
        }
        return {
            "active": active,
            "queue_limit": self.__queue_limit(),
            "pool_losses": self.__pool_losses,
            **counters,
            "worker": pool,
        }

    def shutdown(self):
        executions.cancel_all("关机")
        # 关机前让每个能力自己收尾（比如把后台进程杀掉）
        for entry in self.registry.list():
            dispose = getattr(entry.capability, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass
        if self.__worker_pool is not None:
            self.__worker_pool.shutdown()
            self.__worker_pool = None
        if self.__pool is not None:
            self.__pool.shutdown(wait=False)
            self.__pool = None

    def __ensure_pool(self):
        """允许引擎重启：线程池 shutdown 后不能复用，需要重建。"""
        if self.__pool is None:
            self.__pool = ThreadPoolExecutor(max_workers=self.__workers)
        self.__pool_losses = 0

    # ---------- 内部 ----------
    def __execute(self, item: CapabilityInput):
        if item.error:
            return CapabilityOutput(item.call_id, item.error, ok=False)

        entry = self.registry.get(item.name)
        if entry is None:
            return CapabilityOutput(item.call_id, f"未知能力：{item.name}", ok=False)
        if not self.__entry_available(entry):
            return CapabilityOutput(
                item.call_id,
                f"工具不可用：{item.name}（没安装或没有配置 Key）",
                ok=False,
            )
        scope = _SCOPE.get()
        if scope is not None:
            # 额外会话：以会话自己的场景白名单为准，不受主会话全局启停影响
            if not scope.allows(item.name):
                return CapabilityOutput(
                    item.call_id, f"该会话的场景里没有这个能力：{item.name}", ok=False
                )
        elif not entry.enabled:
            return CapabilityOutput(item.call_id, f"能力已停用：{item.name}", ok=False)

        problem = validate_arguments(entry.spec.parameters, item.arguments or {})
        if problem:
            return CapabilityOutput(item.call_id, problem, ok=False)

        execution = executions.current()
        if self.__worker_pool is None:
            self.__worker_pool = WorkerPool()
        if self.__worker_pool.enabled() and item.name in WORKER_NAMES:
            result = self.__worker_pool.run(
                item.name, item.arguments or {}, execution
            )
            if result is not None:
                return CapabilityOutput(
                    item.call_id,
                    result.get("content", ""),
                    ok=bool(result.get("ok")),
                    meta={
                        "trust": getattr(entry.spec, "trust", "internal"),
                        "source": item.name,
                        "worker": True,
                    },
                )

        content = entry.capability.run(item.arguments or {})
        meta = {
            "trust": getattr(entry.spec, "trust", "internal"),
            "source": item.name,
        }
        ok = True
        if isinstance(content, CapabilityResult):
            meta.update(content.meta or {})
            ok = bool(content.ok)
            content = content.content
        if not isinstance(content, str):
            content = str(content)
        return CapabilityOutput(item.call_id, content, ok=ok, meta=meta)

    def __postprocess(self, item, output):
        content = output.content or ""
        if len(content) <= self.__inline:
            return output

        path = self.__spill(item, content)
        head = content[:2000]
        tail = content[-1000:] if len(content) > 3000 else ""
        preview = head + ("\n…\n" + tail if tail else "")
        summary = f"{preview}\n…(完整输出 {len(content)} 字符，已落盘：{path})"
        meta = dict(output.meta)
        meta.update({"truncated": True, "path": str(path), "original_size": len(content)})
        return CapabilityOutput(output.call_id, summary, output.ok, meta)

    def __spill(self, item, content):
        # 硬盘体系负责落盘：默认进 数据根/Artifacts/spill（能力产物区，不在工作区；模型按路径读取）
        relative = str(config.get("engine.spill_dir", "") or "").strip()
        if relative and relative != "Session_Storage/spill":
            directory = spill_dir(relative)   # 显式配置仍然尊重（绝对路径 / 数据根相对）
            directory.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(
                c if c.isalnum() or c in "-_." else "_" for c in item.name
            )
            safe_call = "".join(
                c if c.isalnum() or c in "-_." else "_" for c in item.call_id
            )
            path = directory / f"{safe_call}-{safe_name}.txt"
            path.write_text(content, encoding="utf-8")
            return path
        info = disk.artifact(
            f"{item.call_id}-{item.name}", content, suffix=".txt", folder="spill"
        )
        return Path(info["path"])


# 能力体系对象，挂总线上
capabilities = CapabilitySystem()
