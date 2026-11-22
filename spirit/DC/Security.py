"""
安全子体系（CPU 的子体系）：审批 + 审计。

审批：模型要执行能力之前，由这里决定 放行 / 询问 / 拒绝。

两个正交的轴（2026-11-19 拆分）：
  engine.access  = readonly | workspace     「范围」：能碰什么
    readonly   写文件 / 执行命令 / 起进程 → 直接拒绝（不问）
    workspace  允许写（路径仍由沙箱限制）
  engine.approval = ask | auto              「模式」：碰的时候问不问
    ask    写与外部调用要确认；读取不问（默认）
    auto   不再问（沙箱与不可信内容策略仍生效）
  旧值兼容：manual / rules → ask，auto → auto。
  询问 = 调前端接进来的审批回调（CLI / Web）；没接回调时按拒绝处理（安全默认）。

审计：每次判定写一条 JSONL（Logs/audit.jsonl）+ 引擎日志。
"""
import json
import os
import threading
import time

from Config import config
from Log import log
from Paths import log_dir
from Redact import redact
from Turn import turn

MODES = {"ask", "auto"}
LEGACY_MODES = {"manual": "ask", "rules": "ask", "auto": "auto"}
ACCESS = {"readonly", "workspace"}
POLICIES = {"warn", "confirm", "block"}

READONLY = {
    "readFile", "listDir", "searchFiles", "findFiles",
    "sessionSearch", "todoRead", "processList", "processOutput",
}
# 兜底用的外部调用（Engine 会注入真实 resolver；没注入时按这里判）
EXTERNAL = {"fetchUrl", "webSearch"}


class Security:
    def __init__(self):
        self.__approver = None
        self.__cancel_approver = None
        self.__side_effect = None
        self.__lock = threading.Lock()
        self.__untrusted = None
        self.__audit_broken = False
        self.__access_scope = "once"

    def set_side_effect_resolver(self, resolver):
        """由 Engine 注入：fn(name) -> read / write / external。"""
        self.__side_effect = resolver

    def __effect(self, name):
        """read / write / external；拿不到就按名字兜底。"""
        resolver = self.__side_effect
        if resolver is not None:
            try:
                value = str(resolver(name) or "")
                if value in {"read", "write", "external"}:
                    return value
            except Exception:
                pass
        if name in EXTERNAL:
            return "external"
        return "read" if name in READONLY else "write"

    def __readonly(self, name):
        return self.__effect(name) in {"read", "external"}

    # ---------- 接线 ----------
    def set_approver(self, approver, cancel=None):
        """接审批回调；cancel 用来取消正在等的审批（停止 / 关机）。"""
        self.__approver = approver
        self.__cancel_approver = cancel

    def cancel_pending(self):
        callback = self.__cancel_approver
        if callback is None:
            return
        try:
            callback()
        except Exception:
            pass

    @property
    def mode(self):
        forced = os.environ.get("SPIRIT_APPROVAL", "").strip().lower()
        if forced in MODES:
            return forced
        raw = config.get("engine.approval", "ask")
        value = str(raw).lower()
        value = LEGACY_MODES.get(value, value)
        return value if value in MODES else "ask"

    @property
    def access(self):
        value = str(config.get("engine.access", "workspace")).lower()
        return value if value in ACCESS else "workspace"

    @property
    def untrusted_policy(self):
        value = str(config.get("engine.untrusted_policy", "confirm")).lower()
        return value if value in POLICIES else "confirm"

    # ---------- 不可信内容标记 ----------
    def note_untrusted(self, source=""):
        """上一批工具结果里有外部内容：后续高风险调用要升级处理。"""
        with self.__lock:
            self.__untrusted = {
                "source": str(source or "工具结果"),
                "time": time.strftime("%H:%M:%S"),
            }

    def clear_untrusted(self):
        with self.__lock:
            self.__untrusted = None

    @property
    def audit_broken(self):
        return bool(self.__audit_broken)

    @property
    def untrusted(self):
        with self.__lock:
            return dict(self.__untrusted) if self.__untrusted else None

    # ---------- 访问授权（沙箱越界时问用户） ----------
    @property
    def access_scope(self):
        """上一次访问授权是「仅本次」还是「本次运行都允许」。"""
        return self.__access_scope

    def request_access(self, capability, call_id, info):
        """工作区外访问：问用户要不要允许这一次。返回 bool。"""
        approver = self.__approver
        path = str((info or {}).get("target") or "")
        reason = str((info or {}).get("message") or "")
        if approver is None:
            return False
        request = {
            "call_id": call_id,
            "name": capability,
            "arguments": "",
            "kind": "access",
            "path": path,
            "reason": reason,
            "mode": self.mode,
            "access": self.access,
            "untrusted": False,
            "source": "",
            "time": time.strftime("%H:%M:%S"),
        }
        self.__access_scope = "once"
        try:
            decision = approver(request)
        except Exception:
            return False
        if isinstance(decision, tuple):
            allowed = bool(decision[0])
            if len(decision) > 2 and str(decision[2]).lower() == "session":
                self.__access_scope = "session"
        else:
            allowed = bool(decision)
        self.__audit_write(
            f"access:{capability}", {"path": path}, call_id, allowed,
            "用户允许本次访问" if allowed else "用户拒绝本次访问",
            untrusted=False, source="", policy="access",
        )
        return allowed

    # ---------- 判定 ----------
    def check(self, name, arguments, call_id="", approved=False):
        """返回 (allowed, reason)。可能阻塞（等用户回答）。

        approved=True 表示「这次调用刚在访问授权里被用户允许过」——
        范围（readonly）、不可信内容、审计坏掉这些硬策略仍然生效，只省掉重复的审批弹窗。
        """
        mode = self.mode
        access = self.access
        policy = self.untrusted_policy
        state = self.untrusted
        effect = self.__effect(name)
        dangerous = effect == "write"          # 会改东西 / 执行
        risky = effect in {"write", "external"}  # 模式 = ask 时要问的
        tainted = bool(state and dangerous)

        if access == "readonly" and dangerous:
            allowed = False
            reason = ("当前范围是「查看」：不执行命令、不改文件。要读代码或文件，请改用 readFile / listDir / searchFiles / findFiles（路径需在工作区或「可访问的路径」里）")
        elif tainted and policy == "block":
            allowed = False
            reason = f"不可信内容之后的高风险调用已阻止（来源：{state['source']}）"
        elif dangerous and self.__audit_broken:
            # 审计写不进去：高风险操作不再"静默放行"，要么问用户、要么拒绝
            approver = self.__approver
            if approver is None:
                allowed = False
                reason = "审计不可用，高风险操作按安全默认拒绝"
            else:
                allowed, reason = True, "审计不可用，已让用户确认"
                try:
                    decision = approver({
                        "call_id": call_id,
                        "name": name,
                        "arguments": str(arguments or "")[:2000],
                        "mode": mode,
                        "access": access,
                        "untrusted": tainted,
                        "source": state["source"] if tainted else "",
                        "audit_broken": True,
                        "time": time.strftime("%H:%M:%S"),
                    })
                except Exception as error:
                    allowed, reason = False, f"审批异常：{error}"
                else:
                    if isinstance(decision, tuple):
                        allowed, reason = bool(decision[0]), str(decision[1])
                    else:
                        allowed = bool(decision)
                        reason = "用户允许" if allowed else "用户拒绝执行该能力"
        elif mode == "auto":
            # 自动模式 = 完全自动（用户 2026-11-20 定）：不可信内容之后也放行，只留审计；
            # 「阻止」是用户显式选的安全策略，仍然生效。
            allowed = True
            reason = "auto" + ("（不可信内容之后，仅审计）" if tainted else "")
        elif not risky:
            allowed, reason = True, "readonly"
        elif approved:
            allowed, reason = True, "用户已允许本次访问"
        else:
            approver = self.__approver
            if approver is None:
                allowed = False
                reason = (
                    "不可信内容之后的高风险调用；没有接入审批，按安全默认拒绝"
                    if tainted else "没有接入审批，按安全默认拒绝"
                )
            else:
                request = {
                    "call_id": call_id,
                    "name": name,
                    "arguments": str(arguments or "")[:2000],
                    "mode": mode,
                    "access": access,
                    "untrusted": tainted,
                    "source": state["source"] if tainted else "",
                    "time": time.strftime("%H:%M:%S"),
                }
                try:
                    decision = approver(request)
                except Exception as error:
                    allowed, reason = False, f"审批异常：{error}"
                else:
                    if isinstance(decision, tuple):
                        allowed, reason = bool(decision[0]), str(decision[1])
                    else:
                        allowed = bool(decision)
                        reason = "用户允许" if allowed else "用户拒绝执行该能力"

        self.__audit_write(
            name, arguments, call_id, allowed, reason,
            untrusted=tainted,
            source=state["source"] if tainted else "",
            policy=policy,
        )
        return allowed, reason

    # ---------- 审计 ----------
    def __audit_write(
        self, name, arguments, call_id, allowed, reason,
        untrusted=False, source="", policy="warn",
    ):
        secrets = [config.get("llm.api_key", "")]
        line = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "turn": turn.current(),
            "capability": name,
            "call_id": call_id,
            "arguments": redact(str(arguments or "")[:500], extra=secrets),
            "allowed": bool(allowed),
            "reason": redact(reason, extra=secrets),
            "untrusted": bool(untrusted),
            "source": source if untrusted else "",
            "policy": policy,
        }
        try:
            audit = log_dir() / "audit.jsonl"   # 按当前数据根解析（数据根可换）
            audit.parent.mkdir(parents=True, exist_ok=True)
            with self.__lock:
                with open(audit, "a", encoding="utf-8") as file:
                    file.write(json.dumps(line, ensure_ascii=False) + "\n")
            self.__audit_broken = False
        except Exception as error:
            self.__audit_broken = True
            log.error("Security", f"审计写入失败：{error}")
        log.info("Security", f"{'ALLOW' if allowed else 'DENY'} {name} ({reason})")


security = Security()
