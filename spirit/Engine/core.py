"""
Agent 通用计算机的引擎（对外门面）

外部只通过这里使用引擎，不碰内部体系。
"""
import json
import os
import threading
import time
from pathlib import Path

from AgentStart import client
from Engine.Sessions import SessionRuntime
from Bus import NT, keys
from Config import config
from Disk import disk
from Config import Providers
from Config import Balances
from GPU import gpu
from Log import log
from Memory import mem
from Memory.Persist import persist
from Paths import config_file, home as data_home, session_dir, set_home
from Render import render
import Scenarios
from Scenarios import scope as scope_tools
from Usage import report as usage_report
from Capabilities import capabilities
from UserInput import userinput
from DC import DC
from DC.Security import security


class Engine:
    def __init__(self, home=None, workdir=None):
        """建一个引擎实例。

        home    数据根（会话 / 日志 / spill / 审计）；None = 环境变量 / 默认规则
        workdir 默认工作目录；None = 配置里的 engine.workdir，再没有就跟随启动目录

        两个参数都是**实例级**的：桌面壳 / 嵌入方在这里注入，引擎自己不猜路径。
        """
        set_home(home)
        config.load()
        Providers.sync_active(config)   # 顶层 llm.* 和 providers 对账（不落盘）

        # 工作目录：参数 > SPIRIT_WORKDIR（子进程模式）> 配置文件 > 数据根/workspace
        # 不再回落到启动目录：源码运行时启动目录就是源码目录，模型能改到 Spirit 自己
        workdir = workdir or os.environ.get("SPIRIT_WORKDIR")
        if not workdir:
            workdir = str(config.get("engine.workdir", "") or "")
        if not workdir:
            workdir = str(Path(data_home()) / "workspace")
            Path(workdir).mkdir(parents=True, exist_ok=True)
        config.set("engine.workdir", str(Path(workdir).expanduser().resolve()))
        if not config.get("engine.default_workspace"):
            config.set("engine.default_workspace", str(config.get("engine.workdir")))

        # 前面这些在 import 时读过路径，这里按新根重新绑定
        log.rebind()
        persist.rebind()
        DC.refresh_config()
        capabilities.rebind()
        security.set_side_effect_resolver(capabilities.side_effect)

        # 装配：CPU 只拿句柄，不 import 具体体系（判据 4 的同步形态）
        # 故障转移的"换一家"也走注入：Engine 管配置和客户端，CPU 只管什么时候换
        DC.attach(
            gpu=gpu, memory=mem, input_source=userinput,
            switch_provider=self.__switch_provider,
        )

        # 能力子集跟着场景走（提示词是 GPU 每轮按场景读的）
        scenario = Scenarios.get_scenario(
            config.get("engine.scenario", Scenarios.DEFAULT_SCENARIO)
        )
        if scenario is None:
            config.set("engine.scenario", Scenarios.DEFAULT_SCENARIO)
            scenario = Scenarios.get_scenario(Scenarios.DEFAULT_SCENARIO)
        if scenario is not None:
            capabilities.apply_scenario(
                Scenarios.capabilities_for(scenario["id"]) or []
            )

        self.__started = False
        self.__session_lock = threading.RLock()
        self.__runtimes = {}
        self.__runtime_by_path = {}
        self.__display_sink = None
        self.__approver = None
        self.__approver_cancel = None

    # ---------- 能力插槽 ----------
    def register_capability(self, capability, config=None):
        """加一个能力：需要 spec() + run(arguments)；可选 configure / setup / dispose。"""
        return capabilities.register(capability, config=config)

    def capabilities(self):
        """当前登记的能力（名字 / 是否启用 / 来源），给前端或诊断用。"""
        return [
            {
                "name": entry.name,
                "enabled": entry.enabled,
                "source": entry.source,
            }
            for entry in capabilities.registry.list()
        ]

    # ---------- 前端适配（显示 / 输入） ----------
    def attach_display(self, sink, console=True):
        """接一个显示出口：sink 收 dict 事件；console=False 关掉控制台输出。"""
        render.set_console(console)
        self.__display_sink = sink
        render.add_sink(sink)
        for runtime in self.__runtimes.values():
            self.attach_session_sink(runtime)

    def attach_session_sink(self, runtime):
        sink = self.__display_sink
        if sink is None:
            return

        def tagged(event, sid=runtime.id):
            item = dict(event)
            item["session"] = sid
            sink(item)

        runtime.render.add_sink(tagged)

    def approver_for(self, runtime):
        """额外会话的审批：带上 session 信息，让前端知道是谁在等。"""
        def approve(request):
            approver = self.__approver
            if approver is None:
                return False
            payload = dict(request)
            payload["session"] = runtime.id
            payload["session_title"] = runtime.title
            return approver(payload)

        return approve

    @property
    def capability_side_effect(self):
        return capabilities.side_effect

    @property
    def switch_provider(self):
        return self.__switch_provider

    def set_input_source(self, source):
        """换用户输入源：回调返回字符串；抛 EOFError 表示关机。"""
        userinput.set_source(source)

    # ---------- 安全（审批 / 审计） ----------
    def set_approver(self, approver, cancel=None):
        """接审批回调：fn(request) -> bool 或 (bool, reason)。"""
        self.__approver = approver
        self.__approver_cancel = cancel
        security.set_approver(approver, cancel)

    @property
    def approval_mode(self):
        return security.mode

    def set_approval(self, mode):
        """切换操作模式：ask（要问）/ auto（自动）。旧值 manual / rules 归一成 ask。"""
        mode = str(mode or "").lower()
        mode = {"manual": "ask", "rules": "ask"}.get(mode, mode)
        if mode not in {"ask", "auto"}:
            raise ValueError("未知操作模式")
        config.set("engine.approval", mode)
        config.save()
        log.info("Engine", f"approval -> {mode}")
        return mode

    def set_access(self, access):
        """切换工作范围：readonly（查看）/ workspace（可修改）。"""
        access = str(access or "").lower()
        if access not in {"readonly", "workspace"}:
            raise ValueError("未知工作范围")
        config.set("engine.access", access)
        config.save()
        log.info("Engine", f"access -> {access}")
        return access

    # ---------- 沙箱：额外可访问路径 ----------
    def sandbox_paths(self):
        return [str(item) for item in (config.get("engine.sandbox.allow_paths", []) or [])]

    def set_sandbox_paths(self, paths):
        """设置工作区之外还能访问的文件夹（文件能力 + 命令）。

        配合「查看」范围 = 只读访问；配合「可修改」= 可读写。
        路径必须是已存在的绝对路径；不存在的直接拒绝（避免手滑写成空路径）。
        """
        cleaned = []
        for item in paths or []:
            raw = str(item or "").strip()
            if not raw:
                continue
            path = Path(raw).expanduser()
            if not path.is_absolute():
                raise ValueError(f"需要绝对路径：{raw}")
            if not path.exists():
                raise ValueError(f"路径不存在：{raw}")
            resolved = str(path.resolve())
            if resolved not in cleaned:
                cleaned.append(resolved)
        config.set("engine.sandbox.allow_paths", cleaned)
        config.save()
        capabilities.reload_sandbox()
        log.info("Engine", f"sandbox paths -> {len(cleaned)}")
        return cleaned

    # ---------- 实例路径 ----------
    @property
    def home(self):
        """当前数据根（会话 / 日志 / spill / 审计都在它下面）。"""
        return str(data_home())

    @property
    def workdir(self):
        """当前默认工作目录（能力执行 / 相对路径的基准）。"""
        return str(config.get("engine.workdir", "") or os.getcwd())

    @property
    def session_dir(self):
        return str(session_dir())

    @property
    def config_path(self):
        return str(config_file())

    # ---------- 工作区 ----------
    def workspaces(self):
        """默认工作区 + 自定义工作区；当前生效的标 current。"""
        current = self.workdir
        default = str(config.get("engine.default_workspace", "") or current)
        items = [{"name": "默认工作区", "path": default, "default": True}]

        extras = config.get("engine.workspaces", []) or []
        for raw in extras:
            path = str(raw.get("path") if isinstance(raw, dict) else raw or "")
            name = str(raw.get("name") if isinstance(raw, dict) else "") or Path(path).name
            if not path:
                continue
            if any(item["path"] == path for item in items):
                continue
            items.append({"name": name or path, "path": path})

        for item in items:
            item["current"] = os.path.normcase(item["path"]) == os.path.normcase(current)

        return {
            "items": items,
            "current": current,
            "session_dir": self.session_dir,
            "config_path": self.config_path,
        }

    def add_workspace(self, path, name=None):
        path = str(Path(path).expanduser().resolve())
        if not Path(path).is_dir():
            raise ValueError(f"文件夹不存在：{path}")
        extras = list(config.get("engine.workspaces", []) or [])
        if not any(
            os.path.normcase(str(raw.get("path") if isinstance(raw, dict) else raw))
            == os.path.normcase(path)
            for raw in extras
        ):
            extras.append({"name": str(name or Path(path).name), "path": path})
            config.set("engine.workspaces", extras)
            config.save()
        return self.workspaces()

    def select_workspace(self, path):
        path = str(Path(path).expanduser().resolve())
        if not Path(path).is_dir():
            raise ValueError(f"文件夹不存在：{path}")
        config.set("engine.workdir", path)
        config.save()
        capabilities.rebind()
        log.info("Engine", f"workdir -> {path}")
        return self.workspaces()

    # ---------- 场景 ----------
    @property
    def scenario(self):
        return str(config.get("engine.scenario", Scenarios.DEFAULT_SCENARIO))

    def scenarios(self, session_id=None):
        """场景状态按会话算：新开的会话没记录就不该显示“已锁定”。"""
        session_id = str(session_id or "")
        if session_id and session_id != "primary":
            runtime = self.runtime(session_id)
            if runtime is not None:
                return {
                    "current": runtime.scenario,
                    "locked": runtime.memory.last_seq() > 0,
                    "scenarios": Scenarios.public_scenarios(),
                }
        return {
            "current": self.scenario,
            # 会话开始后场景锁死（不能让旧会话被"看成"别的场景）
            "locked": mem.last_seq() > 0,
            "scenarios": Scenarios.public_scenarios(),
        }

    def __apply_scenario(self, name, with_defaults=False):
        """把场景写进配置 + 能力子集（提示词由 GPU 按配置读）。

        with_defaults=False 用于「加载会话时恢复场景」：只恢复场景本身，
        不覆盖用户当前的审批 / 沙箱等安全默认值。
        """
        item = Scenarios.get_scenario(name or Scenarios.DEFAULT_SCENARIO)
        if item is None:
            return None
        config.set("engine.scenario", item["id"])
        if with_defaults:
            for key, value in Scenarios.defaults_for(item["id"]).items():
                if key == "approval":
                    # 审批模式是全局设置（默认自动）；场景切换不覆盖它
                    continue
                if key == "sandbox" and isinstance(value, dict):
                    for sub, sub_value in value.items():
                        config.set(f"engine.sandbox.{sub}", sub_value)
                else:
                    config.set(f"engine.{key}", value)
        config.save()
        capabilities.apply_scenario(
            Scenarios.capabilities_for(item["id"]) or []
        )
        if with_defaults:
            capabilities.reload_sandbox()
        DC.refresh_config()
        log.info("Engine", f"scenario -> {item['id']}")
        return item

    def use_scenario(self, name):
        """切换场景：提示词增量 + 能力子集 + 安全默认值。

        - 只在**会话开始前**可选：已经有消息了 → 拒绝（前端 409）
        - 轮次处理中 → 拒绝
        """
        if DC.turn_active:
            raise RuntimeError("这一轮还在处理，等结束再换场景")
        if mem.last_seq() > 0:
            raise RuntimeError("会话已经开始，场景不能再切换；新建会话时再选")
        item = self.__apply_scenario(name, with_defaults=True)
        if item is None:
            raise ValueError(f"没有这个场景：{name}")
        persist.set_scenario(item["id"])

        public = next(
            (row for row in Scenarios.public_scenarios() if row["id"] == item["id"]),
            {"id": item["id"], "name": item.get("name", item["id"]), "description": ""},
        )
        return {
            "current": item["id"],
            "scenario": public,
            "capabilities": self.capabilities(),
            "settings": self.settings(),
        }

    # ---------- 渗透范围 ----------
    def pentest_scope(self):
        """当前渗透授权范围（目标列表）。"""
        return [str(item) for item in (config.get("engine.pentest_scope", []) or [])]

    def set_pentest_scope(self, items):
        """改渗透授权范围；轮次处理中拒绝（下一轮才生效）。"""
        self.__ensure_idle("修改授权范围")
        if isinstance(items, str):
            items = items.splitlines()
        cleaned = []
        for item in items or []:
            if not str(item or "").strip():
                continue                     # 空行 / 空项忽略，不算非法
            text = scope_tools.validate(item)
            if text not in cleaned:
                cleaned.append(text)
        config.set("engine.pentest_scope", cleaned)
        config.save()
        log.info("Engine", f"pentest scope -> {len(cleaned)} target(s)")
        return cleaned

    # ---------- 模型提供商 ----------
    def providers(self):
        return Providers.list_public(config)

    def save_provider(self, data):
        item = Providers.upsert(config, data)
        item["reloaded"] = self.reload_llm()
        return item

    def delete_provider(self, provider_id):
        Providers.remove(config, provider_id)
        return self.providers()

    def duplicate_provider(self, provider_id):
        item = Providers.duplicate(config, provider_id)
        return {"provider": item, **self.providers()}

    def probe_models(self, data):
        """给设置页用：拿表单里的 Base URL / Key 去问模型列表。

        编辑已有提供商时 Key 留空，就从该提供商（或它的环境变量）取。
        """
        base_url = str(data.get("base_url") or "").strip()
        api_key = str(data.get("api_key") or "").strip()
        provider_id = str(data.get("id") or "").strip()
        kind = str(data.get("kind") or "").strip()
        auth = str(data.get("auth") or "").strip()
        if not api_key and provider_id:
            item = next(
                (entry for entry in Providers.providers_of(config)
                 if entry["id"] == provider_id),
                None,
            )
            if item is not None:
                # 只在端点没改的情况下复用已存的 Key，避免把 Key 发到任意新地址
                stored = str(item.get("base_url") or "").strip().rstrip("/")
                same_base = (
                    bool(stored)
                    and base_url.rstrip("/").lower() == stored.lower()
                )
                if same_base:
                    api_key = str(item.get("api_key") or "")
                    env_name = str(item.get("api_key_env") or "")
                    if not api_key and env_name:
                        api_key = os.environ.get(env_name, "")
                    kind = kind or str(item.get("kind") or "")
                    auth = auth or str(item.get("auth") or "")
        return Providers.probe_models(base_url, api_key, kind or "openai", auth or "token")

    def reorder_providers(self, ordered_ids):
        """拖拽排序：按给定 id 顺序重排（照抄 cc-switch 的 sortIndex）。"""
        return Providers.reorder(config, ordered_ids)

    def check_provider(self, data):
        """连通性测试：照 cc-switch，只测 base URL 可达，不验鉴权 / 不发模型请求。"""
        data = data or {}
        base_url = str(data.get("base_url") or "").strip()
        if not base_url:
            item = Providers.find(config, data.get("id"))
            base_url = str(item.get("base_url") or "")
        result = Providers.check(base_url)
        return {"base_url": base_url, **result}

    def speed_test(self, data):
        """端点测速：传一组 URL（表单里的候选端点），返回每个的延迟和最快的。"""
        urls = (data or {}).get("urls") or []
        if not urls:
            item = Providers.find(config, (data or {}).get("id"))
            urls = list(item.get("endpoints") or [item.get("base_url")])
        return Providers.speed_test(urls, (data or {}).get("timeout"))

    def query_balance(self, data):
        """余额查询：按已存的提供商配置调对应供应商的余额接口。"""
        item = Providers.find(config, (data or {}).get("id"))
        result = Balances.query(item)
        result["provider"] = {
            "id": item["id"],
            "name": item.get("name") or item["id"],
        }
        return result

    def export_providers(self):
        """导出全部提供商（含明文 Key）——给设置页的「导出」用，由用户自己保管。"""
        items = Providers.providers_of(config)
        return {
            "format": "spirit-providers",
            "version": 1,
            "active": Providers.active_id(config, items),
            "model": str(config.get("llm.model") or ""),
            "providers": [dict(item) for item in items],
        }

    def import_providers(self, data):
        """导入提供商（Spirit 导出格式 / 裸数组都收）。

        - 先整批校验，再写入：不会出现"前几条写进去、后面炸掉"的半套导入
        - 同 id 覆盖时，如果 **base_url 变了但没带新 Key**：清空旧 Key（防止把 Key 发往新地址）
        - 不自动切换当前提供商
        """
        payload = data or {}
        items = payload.get("providers") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("导入数据里没有 providers 列表")

        existing = {item["id"]: item for item in Providers.providers_of(config)}
        prepared = []
        errors = []
        warnings = []
        for raw in items:
            if not isinstance(raw, dict):
                errors.append("跳过一条非对象")
                continue
            data_item = dict(raw)
            label = str(data_item.get("name") or data_item.get("id") or "?")
            pid = str(data_item.get("id") or "").strip()
            old_item = existing.get(pid) if pid else None
            if old_item is not None:
                kind = Providers._kind(data_item.get("kind"), old_item.get("kind") or "openai")
                new_base = Providers.normalize_base(kind, data_item.get("base_url"))
                old_base = str(old_item.get("base_url") or "").rstrip("/").lower()
                has_key = bool(str(data_item.get("api_key") or "").strip())
                if new_base and new_base.lower() != old_base and not has_key:
                    data_item["clear_key"] = True
                    warnings.append(f"{label}：地址变了但没带新 Key，旧 Key 已清空")
            try:
                Providers.validate(data_item)
            except ValueError as error:
                errors.append(f"{label}：{error}")
                continue
            prepared.append(data_item)

        imported = 0
        for data_item in prepared:
            try:
                Providers.upsert(config, data_item)
                imported += 1
            except ValueError as error:
                errors.append(f"{data_item.get('name') or '?'}：{error}")
        return {
            "imported": imported,
            "errors": errors,
            "warnings": warnings,
            **self.providers(),
        }

    def activate_provider(self, provider_id, model=None):
        model = Providers.activate(config, provider_id, model)
        ok = self.reload_llm()
        return {"model": model, "reloaded": ok, **self.providers()}

    def reload_llm(self):
        """按当前配置重建模型客户端（下一轮生效）。"""
        if not self.__started:
            return True
        client.Create()
        report = NT.get(keys.AGENT_START)
        return bool(report is not None and report.SI)

    def __switch_provider(self, provider_id):
        """故障转移用：切到指定提供商并重建客户端（返回是否成功）。

        由 DC.attach 注入 CPU；CPU 只负责"什么时候换"，配置与客户端归 Engine。
        """
        try:
            model = Providers.activate(config, provider_id)
        except Exception as error:
            log.warning("Engine", f"failover switch failed: {error}")
            return False
        client.Create()
        report = NT.get(keys.AGENT_START)
        ok = bool(report is not None and report.SI)
        log.warning(
            "Engine",
            f"failover switch -> {provider_id} model={model} ok={ok}",
        )
        return ok

    def failover_state(self):
        """熔断器快照（诊断 / 设置页显示用）。"""
        from DC.Failover import failover
        return {
            "enabled": failover.enabled(),
            "queue": failover.queue(),
            "state": failover.snapshot(),
        }

    # ---------- 生命周期 ----------
    def start(self):
        """开机：BIOS 自检 -> 恢复会话 -> 能力体系上总线 -> CPU 注册控制信号"""
        log.info("Engine", f"approval mode = {security.mode} (config={config.get('engine.approval')})")
        client.Create()
        disk.ensure()                         # 硬盘主体系：开机必须有
        if config.get("engine.restore", True):
            restored = persist.restore_latest()   # 上一次会话读回内存（只读最新一份）
            if restored:
                scenario = persist.scenario or Scenarios.DEFAULT_SCENARIO
                self.__apply_scenario(scenario, with_defaults=False)
                persist.set_scenario(scenario)   # 老会话补写 sidecar
        NT.register(keys.SESSION_LOCK, self.__session_lock, replace=True)
        NT.register(keys.DISK, disk)
        NT.register(keys.CAPABILITIES, capabilities)
        render.start()          # 显示体系：常驻执行流（从当前数据末尾开始看）
        DC.boot()
        # 上次被强杀时来不及释放浏览器 Space：开机后台补一次
        try:
            from Capabilities import Browser
            threading.Thread(
                target=Browser.cleanup_stale_spaces, name="ego-cleanup", daemon=True
            ).start()
        except Exception:
            pass
        self.__started = bool(DC.start)
        return self.__started

    def run(self):
        """进入对话循环（阻塞，直到 exit / EOF）。"""
        if not self.__started:
            return
        try:
            DC.run()
        finally:
            render.shutdown()

    def stop(self):
        """请求关机：取消当前轮的流 / 工具 / 审批 / 摘要，跑完这一轮就退出。"""
        for runtime in list(self.__runtimes.values()):
            try:
                runtime.stop()
            except Exception:
                pass
        DC.start = False
        DC.interrupt()

    def interrupt(self):
        """中断当前轮（不停机）：停模型流 + 停正在跑的工具。"""
        DC.interrupt()

    def running(self, session_id="primary"):
        """当前会话在跑的能力调用（名字 / 已跑秒数 / 超时）。"""
        return capabilities.running(session_id)

    def reload_sandbox(self):
        """边界配置改了之后重读（设置页切沙箱开关时用）。"""
        return capabilities.reload_sandbox()

    def context(self):
        """上一次出包的上下文构成：系统提示词 / 工具定义 / 对话消息。

        三块按字符估算；如果上一次请求有真实 input_tokens，就按比例校准，
        让总和对得上统计条里的真实用量。
        """
        stats = gpu.context_stats()
        try:
            last = self.usage().get("last") or {}
            real = int(last.get("input", 0) or 0)
        except Exception:
            real = 0
        if real > 0 and stats.get("total", 0) > 0:
            ratio = real / stats["total"]
            parts = {
                key: max(0, round(int(stats.get(key, 0)) * ratio))
                for key in ("system", "tools", "messages")
            }
            drift = real - sum(parts.values())
            parts["messages"] = max(0, parts["messages"] + drift)
            stats.update(parts)
            stats["total"] = real
            window = int(stats.get("window", 0) or 0)
            stats["percent"] = (real / window * 100) if window else 0
            stats["calibrated"] = True
        return stats

    def usage(self):
        """真实用量账本：本轮 / 会话的 token、成本、最后一次请求、预算。"""
        mem.flush()
        keys = (
            "max_turn_tokens", "max_session_tokens",
            "max_turn_cost", "max_session_cost",
        )
        budgets = {key: config.get(f"engine.{key}", 0) or 0 for key in keys}
        # 用量记录走视图（退役不会清掉它），轮次边界显式给最后一条 user 的 seq
        return usage_report(
            mem.view("usage"),
            window=Providers.active_value(config, "context_window", 128000),
            budgets=budgets,
            last_user=mem.last_seq("user"),
        )

    def set_thinking(self, on, effort=None):
        """设置思考开关 / 强度（下一轮开始生效）。"""
        DC.set_thinking(on, effort)

    @property
    def thinking(self):
        return bool(DC.thinking)

    @property
    def effort(self):
        return DC.effort

    @property
    def is_running(self):
        return self.__started and DC.start

    @property
    def model(self):
        """当前模型名（来自 config.llm.model）。"""
        return str(config.get("llm.model", ""))

    @property
    def build(self):
        """桌面版注入的构建信息（源码直接运行时为空）。"""
        return str(os.environ.get("SPIRIT_BUILD", "") or "")

    # ---------- 内核健康 ----------
    def kernel_stats(self, session_id=None):
        from Capabilities import Browser
        from DC.Reconnect import reconnect

        sid = str(session_id or "primary")
        return {
            **capabilities.stats(),
            # 当前会话还在执行的工具数：轮次收尾必须等它归零
            "running": len(capabilities.running(sid)),
            "browser": Browser.health(),
            "retry": reconnect.snapshot(),
            "cpu": {
                "state": getattr(DC, "state", "idle"),
                "turn_active": bool(getattr(DC, "turn_active", False)),
            },
        }

    # ---------- 硬盘 ----------
    def disk_info(self):
        return {
            "areas": disk.usage(),
            "roots": {name: str(path) for name, path in disk.roots().items()},
        }

    def disk_clear(self, area):
        references = None
        if str(area) == "uploads":
            # 内存里的引用由引擎收集，Disk 不反向依赖 Memory（内核边界）
            references = set()
            for record in mem.snapshot():
                try:
                    text = json.dumps(record.payload, ensure_ascii=False, default=str)
                except Exception:
                    continue
                references.update(disk.image_names(text))
        return disk.clear(
            area, references=references, keep_path=self.current_session()
        )

    def settings(self):
        """引擎当前设置（场景 / 思考 / 强度 / 模型 / 运行状态）。"""
        return {
            "scenario": self.scenario,
            "thinking": self.thinking,
            "effort": self.effort,
            "model": self.model,
            "build": self.build,
            "started": self.__started,
            "running": self.is_running,
        }

    def status(self):
        """引擎状态 + 当前会话文件 + 显示线程健康。"""
        return {
            **self.settings(),
            "session": persist.current_path,
            "render": render.status(),
        }

    # ---------- 数据接口 ----------
    def transcript(self, compact=False):
        """当前会话翻译成大模型 input 的形式（默认只读快照）。

        compact=True 才允许触发摘要（会发模型请求并写一条 SUMMARY）；
        默认 false 保证 getter 不改数据、不花钱。
        """
        return list(gpu.build_context(compact=compact).messages)

    # ---------- 额外会话（K4b） ----------
    def open_runtime(self, path=None, limit_turns=40, title=""):
        """打开/复用一个额外会话运行时；path 为空表示新建会话。"""
        path = str(path or "")
        if path:
            existing = self.__runtime_by_path.get(path)
            if existing is not None:
                return existing
        runtime = SessionRuntime(self, path=path, title=title)
        if path:
            runtime.load(path)
        runtime.start()
        self.__runtimes[runtime.id] = runtime
        if path:
            self.__runtime_by_path[path] = runtime
        self.attach_session_sink(runtime)
        return runtime

    def runtime(self, session_id):
        return self.__runtimes.get(str(session_id or ""))

    def close_runtime(self, session_id=None, path=None):
        """关掉一个额外会话运行时（线程 / 渲染 / 执行都收掉），返回它的 id。

        只停内存里的运行时，不动磁盘文件；文件要不要删由调用方决定。
        """
        runtime = self.runtime(session_id) if session_id else None
        if runtime is None and path:
            runtime = self.runtime_for_path(path)
        if runtime is None:
            return None
        try:
            runtime.stop()
        except Exception:
            pass
        self.__runtimes.pop(runtime.id, None)
        for key, value in list(self.__runtime_by_path.items()):
            if value is runtime:
                self.__runtime_by_path.pop(key, None)
        return runtime.id

    def runtime_for_path(self, path):
        path = str(path or "")
        found = self.__runtime_by_path.get(path)
        if found is not None:
            return found
        for runtime in self.__runtimes.values():
            current = runtime.current_path
            if current and current == path:
                self.__runtime_by_path[path] = runtime
                return runtime
        return None

    @property
    def primary_path(self):
        return persist.current_path

    @property
    def primary_running(self):
        return bool(DC.turn_active)

    def runtime_list(self):
        items = []
        for runtime in self.__runtimes.values():
            path = runtime.current_path
            try:
                mtime = Path(path).stat().st_mtime if path else time.time()
            except OSError:
                mtime = time.time()
            items.append({
                "id": runtime.id,
                "title": runtime.display_title,
                "path": path,
                "running": runtime.running,
                "queued": runtime.queue_size,
                "live": True,
                "records": runtime.memory.last_seq(),
                "mtime": mtime,
            })
        return items

    @property
    def primary_title(self):
        return persist.title or mem.title_hint() or "会话"

    def primary_info(self):
        """主会话（还在内存里、可能没落盘）的侧栏条目。"""
        path = self.primary_path
        try:
            mtime = Path(path).stat().st_mtime if path else time.time()
        except OSError:
            mtime = time.time()
        try:
            records = mem.last_seq()
        except Exception:
            records = 0
        return {
            "id": "primary",
            "title": self.primary_title,
            "path": path,
            "running": self.primary_running,
            "queued": 0,
            "live": True,
            "records": records,
            "mtime": mtime,
        }

    def history_events(self):
        """当前会话还原成给人看的显示事件（全量，测试 / 旧接口用）。"""
        return render.history(mem.snapshot())

    def history_window(self, limit_turns=40):
        """页面回放窗口：只取最近 N 轮（从 user 记录切）。

        返回 {events, has_more, limit}——页面默认只渲染最近 N 轮，
        上翻“加载更早”时把 limit 加大重新取（AF 之后改成真正按磁盘分页）。
        """
        from Memory.Addresses import USER as USER_ADDRESS

        try:
            limit = max(1, min(int(limit_turns), 500))
        except (TypeError, ValueError):
            limit = 40
        records = mem.snapshot()
        user_positions = [
            index for index, record in enumerate(records)
            if record.address == USER_ADDRESS
        ]
        if mem.records_floor() > 0 and len(user_positions) < limit:
            # 冷记录已经退役：要翻得更早，从磁盘按区间读回（稀疏索引，不全量解析）
            disk = persist.read_records(limit_turns=limit)
            if disk:
                # 按 seq 去重合并：磁盘尾段可能和内存热记录有重叠
                by_seq = {record.seq: record for record in disk}
                for record in records:
                    by_seq.setdefault(record.seq, record)
                records = [by_seq[seq] for seq in sorted(by_seq)]
                user_positions = [
                    index for index, record in enumerate(records)
                    if record.address == USER_ADDRESS
                ]
        start = user_positions[-limit] if len(user_positions) > limit else 0
        return {
            "events": render.history(records[start:]),
            "has_more": start > 0,
            "limit": limit,
        }

    def __ensure_idle(self, action):
        """会话类操作只在轮次边界：正在处理一轮时拒绝（Web 映射 409）。

        不加这个守卫的后果不是“丢一次写”：在飞那一轮的剩余记录会追加进
        刚切过去的那份历史会话文件（persist 的 path / 水位已被换掉）。
        """
        if DC.turn_active:
            raise RuntimeError(f"这一轮还在处理，等结束再{action}")

    def clear_memory(self):
        """清空内存（新会话）。"""
        if not self.__session_lock.acquire(blocking=False):
            raise RuntimeError("这一轮还在处理，等结束再新建会话")
        try:
            self.__clear_memory_locked()
        finally:
            self.__session_lock.release()

    def __clear_memory_locked(self):
        self.__ensure_idle("新建会话")
        render.sync(1.0)      # 同步点：先把当前显示数据消费完
        mem.flush()
        # 还没落盘的对话先存一份：清空后侧栏才能看到、也才回得去
        if mem.last_seq() > 0:
            mem.save()
        mem.clear()
        persist.reset()
        render.reset_position()

    def load_session(self, path, limit_turns=None):
        """切换会话：清空后读入指定会话文件，返回给人看的回放事件。

        场景跟着会话走：sidecar 记的是哪个场景就恢复哪个（老会话没有 sidecar
        → 按默认场景，并补写一份）。只恢复场景本身，不动审批 / 沙箱默认值。
        limit_turns 给了就返回窗口 dict（Web 用），否则返回全量列表（旧调用方）。
        """
        if not self.__session_lock.acquire(blocking=False):
            raise RuntimeError("这一轮还在处理，等结束再切换会话")
        try:
            return self.__load_session_locked(path, limit_turns)
        finally:
            self.__session_lock.release()

    def __load_session_locked(self, path, limit_turns=None):
        self.__ensure_idle("切换会话")
        render.sync(1.0)      # 同步点：先把当前显示数据消费完
        mem.flush()
        mem.clear()
        persist.reset()
        persist.load(path)
        scenario = persist.scenario or Scenarios.DEFAULT_SCENARIO
        self.__apply_scenario(scenario, with_defaults=False)
        persist.set_scenario(scenario)   # 老会话补写 sidecar
        self.__last_load_skipped = int(getattr(persist, "last_skipped", 0) or 0)
        render.reset_position()
        if limit_turns is not None:
            return self.history_window(limit_turns)
        return self.history_events()

    def session_warnings(self):
        """最近一次加载会话跳过了多少损坏行（给界面提示用）。"""
        skipped = int(getattr(self, "_Engine__last_load_skipped", 0) or 0)
        return [f"跳过 {skipped} 行损坏的会话记录"] if skipped else []

    def new_session(self):
        """新会话：清空内存，返回空回放。场景回到"未开始"，可以重新选。"""
        if not self.__session_lock.acquire(blocking=False):
            raise RuntimeError("这一轮还在处理，等结束再新建会话")
        try:
            self.__ensure_idle("新建会话")
            self.clear_memory()
            persist.set_scenario(self.scenario)   # 先按当前选择挂着，首次落盘时写 sidecar
            return []
        finally:
            self.__session_lock.release()

    # ---------- 会话索引 ----------
    def list_sessions(self, limit=50):
        """历史会话列表（新的在前；标题取第一条 user）。"""
        return persist.list_sessions(limit)

    def current_session(self):
        """当前会话文件路径（没落盘时为 None）。"""
        return persist.current_path

    def rename_session(self, path, title):
        """给历史会话改标题。"""
        return persist.rename(path, title)

    def delete_session(self, path):
        """删除历史会话；删的是当前会话就先切到新会话，再删文件。"""
        if self.current_session() and str(path) == self.current_session():
            self.new_session()
        # 额外会话可能正占着这份文件：先关运行时，否则删完还会被它写回来
        self.close_runtime(path=path)
        return persist.delete(path)
