"""SSE 队列：流式片段合并 / 满时优先丢可再生事件 / 正文尾部不丢。"""
import queue
import sys

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))

from WebUI import Output  # noqa: E402

q = Output.subscribe()


def drain():
    items = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items


try:
    # 5000 段正文 → 合并成极少条目，文本完整
    for _ in range(5000):
        Output.publish({"type": "assistant_delta", "text": "x"})
    Output.publish({"type": "assistant_end"})
    items = drain()
    text = "".join(e.get("text", "") for e in items if e["type"] == "assistant_delta")
    assert text == "x" * 5000, len(text)
    assert len(items) <= 3, [e["type"] for e in items]
    assert any(e["type"] == "assistant_end" for e in items)
    print("1. 片段合并 ok：5000 段 ->", len(items), "条")

    # 大量可再生事件灌满后，正文仍然不能丢
    for _ in range(2500):
        Output.publish({"type": "usage"})
    Output.publish({"type": "assistant_delta", "text": "重要"})
    Output.publish({"type": "assistant_end"})
    items = drain()
    assert any(
        e["type"] == "assistant_delta" and e["text"] == "重要" for e in items
    ), "正文被丢了"
    assert any(e["type"] == "assistant_end" for e in items)
    assert len(items) <= 2000, len(items)
    print("2. 满队列优先丢可再生事件 ok")

    # 不同类型不合并，顺序不变
    Output.publish({"type": "reasoning_delta", "text": "想"})
    Output.publish({"type": "assistant_delta", "text": "答"})
    Output.publish({"type": "reasoning_delta", "text": "再想"})
    items = drain()
    assert [e["type"] for e in items] == [
        "reasoning_delta", "assistant_delta", "reasoning_delta"
    ], [e["type"] for e in items]
    print("3. 类型边界 ok")

    # 不同会话的流式片段不能合并成一条（K4b）
    Output.publish({"type": "assistant_delta", "text": "A1", "session": "s1"})
    Output.publish({"type": "assistant_delta", "text": "B1", "session": "s2"})
    Output.publish({"type": "assistant_delta", "text": "A2", "session": "s1"})
    items = drain()
    assert [(e.get("session"), e.get("text")) for e in items] == [
        ("s1", "A1"), ("s2", "B1"), ("s1", "A2")
    ], items
    print("4. 跨会话不合并 ok")
finally:
    Output.unsubscribe(q)

print("\nSSE COALESCE TEST OK")
