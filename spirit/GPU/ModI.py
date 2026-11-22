"""
大模型输入子体系（GPU 渲染体系的子体系）：把加工好的中立消息包发给 provider。

只做三件事：取句柄、取控制信号、把请求交给方言（Provider.Adapter）。
不重试——重试是 CPU 的调度策略（DC/Reconnect）。
"""
from Bus import NT, keys
from Provider import adapter


class ModInput:
    def request(self, bundle):
        """发一次流式请求，返回流（句柄）。"""
        handle = NT.get(keys.LLM)
        if handle is None:
            return None

        ctrl = NT.get(keys.CPU_MOD)
        if ctrl is not None and not ctrl.should_process:
            return None

        capability_system = NT.get(keys.CAPABILITIES)
        schemas = capability_system.schemas() if capability_system is not None else []

        # 思考开关由 CPU 统一调度（总线上的控制对象）
        thinking_ctrl = NT.get(keys.CPU_THINKING)
        thinking_on = bool(thinking_ctrl and thinking_ctrl.should_process)
        effort = getattr(thinking_ctrl, "effort", "medium")

        return adapter.create(handle, bundle, schemas, thinking_on, effort)


modi = ModInput()
