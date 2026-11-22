"""文件类能力测试：写 / 读 / 列 / 替换 / 搜内容 / 找文件 + 错误路径。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-files-")

from Capabilities import CapabilityInput, capabilities  # noqa: E402
from Config import config  # noqa: E402

root = tempfile.mkdtemp(prefix="spirit-fs-root-")
config.set("engine.workdir", root)   # 沙箱边界：把这轮的根当工作区
capabilities.rebind()


def call(cap, **arguments):
    output = capabilities.run([CapabilityInput(
        call_id=f"c-{cap}",
        name=cap,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
        arguments=arguments,
    )])[0]
    return output.content


# 0. 说明都上去了
names = {item["name"] for item in capabilities.schemas()}
print("capabilities:", sorted(names))
assert {"bash", "readFile", "writeFile", "listDir",
        "replaceInFile", "searchFiles", "findFiles"} <= names

# 1. 写
out = call("writeFile", path=f"{root}/a.py", content="def hello():\n    return 1\n")
print("write:", out)
assert out.startswith("已新建"), out

# 2. 读
out = call("readFile", path=f"{root}/a.py")
print("read:", out.replace("\n", " | "))
assert "1  def hello():" in out and "共 2 行" in out, out

# 3. 列
out = call("listDir", path=root)
print("list:", out)
assert "a.py" in out and out.startswith("#")

# 4. 替换（唯一匹配）
out = call("replaceInFile", path=f"{root}/a.py", old_text="return 1", new_text="return 2")
print("replace:", out)
assert "已替换第 1 处" in out
assert "return 2" in call("readFile", path=f"{root}/a.py")

# 5. 替换（找不到）
out = call("replaceInFile", path=f"{root}/a.py", old_text="nope", new_text="x")
assert "没有找到" in out, out

# 6. 搜内容
out = call("searchFiles", pattern="return 2", path=root)
print("search:", out)
assert "a.py:2:" in out, out

# 7. 找文件
out = call("findFiles", name="*.py", path=root)
print("find:", out)
assert "a.py" in out

# 8. 错误路径
assert "文件不存在" in call("readFile", path=f"{root}/nope.txt")
assert "这是文件夹" in call("readFile", path=root)
assert "这是文件" in call("listDir", path=f"{root}/a.py")
assert "正则不合法" in call("searchFiles", pattern="(")

# 9. 缺参数 → 校验拦截
out = capabilities.run([CapabilityInput("c-x", "readFile", "{}", {})])[0]
assert not out.ok and "缺少必填参数" in out.content, out

print("FILES TEST OK")
