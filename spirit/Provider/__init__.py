"""
provider 方言包（共用，不属于任何体系）

为什么单独一个包：ModI（GPU 的子体系）和 ModO（内存的子体系）都要用它，
折给哪一边，另一边就得跨主体系。
"""
from .Adapter import LLMAdapter, ResponsesAdapter, adapter, get_adapter
