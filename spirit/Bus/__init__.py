"""
该包属于中立表体系：体系之间不互相 import，只通过表交换信号 / 资源
"""
# 中立表对象
from .NeutralTable import NT

# 总线的地址（key 词表）
from . import keys
