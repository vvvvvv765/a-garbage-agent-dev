"""
Web 输入源（用户输入体系的子体系）：浏览器发来的输入进队列。

队列里放 None = 关机（对应控制台的 EOF）。
"""
import queue

inputs = queue.Queue()


def source():
    text = inputs.get()
    if text is None:
        raise EOFError
    return text


def attach(engine):
    """把用户输入源换成浏览器队列（只通过引擎的门面接线）。"""
    engine.set_input_source(source)
