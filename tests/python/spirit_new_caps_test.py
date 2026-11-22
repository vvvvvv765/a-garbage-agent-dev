"""后台进程 / 待办 / 历史会话搜索 三个新能力的测试。"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
SESSION_DIR = tempfile.mkdtemp(prefix="spirit-newcaps-")
os.environ["SPIRIT_SESSION_DIR"] = SESSION_DIR

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Capabilities.Processes import processes            # noqa: E402
from Memory import TODO, mem                           # noqa: E402


def call(cap, **arguments):
    return capabilities.run([CapabilityInput(f"c-{cap}", cap, "{}", arguments)])[0]


names = {item["name"] for item in capabilities.schemas()}
print("capabilities:", sorted(names))
assert {"processStart", "processList", "processOutput", "processKill",
        "todoWrite", "todoRead", "sessionSearch"} <= names

# ---------- 后台进程 ----------
out = call("processStart", command="echo hello; sleep 1; echo done")
print("start:", out)
assert "已启动" in out.content

out = call("processList")
print("list:", out.content)
assert "运行中" in out.content

time.sleep(0.5)
out = call("processOutput", id="p1")
print("output1:", out.content.replace("\n", " | "))

time.sleep(1.6)
out = call("processOutput", id="p1", offset=0, limit=50)
print("output2:", out.content.replace("\n", " | "))
assert "hello" in out.content and "done" in out.content and "退出码" in out.content

out = call("processStart", command="sleep 30")
assert "p2" in out.content
out = call("processKill", id="p2")
print("kill:", out.content)
assert "已结束" in out.content
out = call("processList")
assert "已结束" in out.content

# ---------- 待办 ----------
out = call("todoWrite", items=[
    {"text": "扫端口", "status": "in_progress"},
    {"text": "写报告"},
])
print("todo write:", out.content.replace("\n", " | "))
assert "[~]" in out.content and "[ ]" in out.content

out = call("todoRead")
assert "扫端口" in out.content
mem.flush()
assert any(r.address == TODO for r in mem.records()), "todo 没写进数据表"

# ---------- 历史会话搜索 ----------
session = os.path.join(SESSION_DIR, "session-20261118-100000.jsonl")
with open(session, "w", encoding="utf-8") as file:
    file.write(json.dumps({"seq": 1, "address": "user", "payload": "记住暗号是蓝鲸"}, ensure_ascii=False) + "\n")
    file.write(json.dumps({"seq": 2, "address": "assistant", "payload": "好的，暗号是蓝鲸。"}, ensure_ascii=False) + "\n")

out = call("sessionSearch", keyword="蓝鲸")
print("search:", out.content.replace("\n", " | "))
assert "蓝鲸" in out.content and "会话" not in out.content.splitlines()[0]
out = call("sessionSearch", keyword="不存在的词")
assert "没有找到" in out.content

processes.stop_all()
print("NEW CAPS TEST OK")
