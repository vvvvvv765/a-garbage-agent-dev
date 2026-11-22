"""
该包是 GPU 渲染体系（给大模型看的上下文）

子体系：ModI（发送）、Summary（摘要）
"""
from .Bundle import ContextBundle
from .core import gpu, GPURender
from .ModI import modi
