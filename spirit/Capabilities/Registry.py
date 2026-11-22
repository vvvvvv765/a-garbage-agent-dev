"""
能力注册表：能力的登记 / 加载 / 启停 / 注销的唯一入口。

约定：
  - 能力的说明（spec）和对象一起登记，登记完就固定（除非注销重装）
  - 每个能力只有一条记录；重名直接报错
  - 加载既支持现成对象，也支持清单条目 {"module", "class", "config"}
  - 禁用的能力：不出现在 schemas()，也不能执行
"""
import importlib
from dataclasses import dataclass, field

from .Validate import validate_config


class RegistryError(Exception):
    """登记 / 加载失败（重名、依赖不可用、配置不合法）。"""


@dataclass
class Entry:
    name: str
    capability: object
    spec: object
    source: str = ""
    enabled: bool = True
    config: dict = field(default_factory=dict)


class Registry:
    def __init__(self, env):
        """env = 能力体系能注入的依赖表（如 workdir / config / log）。"""
        self.__entries = {}
        self.__env = dict(env)
        # 注册表版本：增删 / 启停 / 重新注入都会 +1。
        # GPU 用它缓存“工具定义”的 token 基数，不必每轮重新序列化全部 schema。
        self.__version = 0

    def __bump(self):
        self.__version += 1

    def version(self):
        return self.__version

    # ---------- 加载 / 登记 ----------
    def load(self, entry):
        """按清单条目加载：{"module": "包.模块", "class": "类名", "config": {...}}"""
        module = importlib.import_module(entry["module"])
        factory = getattr(module, entry["class"])
        capability = factory()
        source = f"{entry['module']}.{entry['class']}"
        return self.add(capability, config=entry.get("config"), source=source)

    def add(self, capability, config=None, source=""):
        """登记一个能力对象。返回它的 spec。"""
        spec = capability.spec()
        if spec.name in self.__entries:
            raise RegistryError(f"能力重名：{spec.name}")

        missing = [name for name in spec.deps if name not in self.__env]
        if missing:
            raise RegistryError(f"{spec.name} 依赖不可用：{', '.join(missing)}")

        config = dict(config or {})
        problem = validate_config(spec.config_schema, config)
        if problem:
            raise RegistryError(f"{spec.name} 配置不合法：{problem}")

        if config and hasattr(capability, "configure"):
            capability.configure(config)
        if spec.deps and hasattr(capability, "setup"):
            capability.setup({name: self.__env[name] for name in spec.deps})

        self.__entries[spec.name] = Entry(
            name=spec.name,
            capability=capability,
            spec=spec,
            source=source or getattr(type(capability), "__module__", ""),
            enabled=True,
            config=config,
        )
        self.__bump()
        return spec

    def remove(self, name):
        """注销；能力有 dispose() 就调它释放资源。"""
        entry = self.__entries.pop(name, None)
        if entry is None:
            return False
        dispose = getattr(entry.capability, "dispose", None)
        if callable(dispose):
            try:
                dispose()
            except Exception:
                pass
        self.__bump()
        return True

    # ---------- 重新注入 ----------
    def rebind(self, env):
        """数据根 / 工作目录变了：更新依赖表，并让声明了 deps 的能力重新 setup。"""
        self.__env = dict(env)
        self.__bump()
        for entry in self.__entries.values():
            deps = entry.spec.deps
            if not deps or not hasattr(entry.capability, "setup"):
                continue
            if any(name not in self.__env for name in deps):
                continue
            try:
                entry.capability.setup({name: self.__env[name] for name in deps})
            except Exception:
                pass

    # ---------- 场景白名单 ----------
    def set_enabled(self, names):
        """按场景的能力白名单整体启停；返回发生变化的名单。"""
        wanted = set(names or [])
        changed = []
        for entry in self.__entries.values():
            enabled = entry.name in wanted
            if entry.enabled != enabled:
                entry.enabled = enabled
                changed.append(entry.name)
        if changed:
            self.__bump()
        return changed

    # ---------- 启停 ----------
    def enable(self, name):
        entry = self.__entries.get(name)
        if entry is None:
            return False
        if not entry.enabled:
            entry.enabled = True
            self.__bump()
        return True

    def disable(self, name):
        entry = self.__entries.get(name)
        if entry is None:
            return False
        if entry.enabled:
            entry.enabled = False
            self.__bump()
        return True

    # ---------- 读 ----------
    def get(self, name):
        return self.__entries.get(name)

    def list(self):
        return list(self.__entries.values())

    def schemas(self, include_disabled=False):
        """给大模型的说明清单（默认只管全局启用的）。

        include_disabled=True 给「会话级白名单」用：全局启停是主会话的场景，
        额外会话按自己的 scope 过滤，不能受主会话切换场景影响。
        """
        return [
            {
                "type": "function",
                "name": entry.spec.name,
                "description": entry.spec.description,
                "parameters": entry.spec.parameters,
            }
            for entry in self.__entries.values()
            if include_disabled or entry.enabled
        ]
