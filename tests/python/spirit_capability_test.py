"""能力体系测试：注册 / 依赖注入 / 配置 / 参数校验 / 启停 / 注销 / 清单加载。"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.environ.get("SPIRIT_SOURCE") or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "spirit"))
os.environ["SPIRIT_SESSION_DIR"] = tempfile.mkdtemp(prefix="spirit-cap-")

from Capabilities import CapabilityInput, CapabilitySpec, capabilities  # noqa: E402

seen = {}


class EchoCap:
    def spec(self):
        return CapabilitySpec(
            name="echo_cap",
            description="把 text 原样返回",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            config_schema={
                "type": "object",
                "properties": {"prefix": {"type": "string"}},
            },
            deps=("workdir",),
        )

    def configure(self, config):
        seen["config"] = config

    def setup(self, deps):
        seen["deps"] = deps

    def run(self, arguments):
        return (seen.get("config", {}).get("prefix", "") or "") + arguments["text"]

    def dispose(self):
        seen["disposed"] = True


# 1. 注册（配置 + 依赖注入）
spec = capabilities.register(EchoCap(), config={"prefix": "P:"})
assert spec.name == "echo_cap"
assert seen["config"] == {"prefix": "P:"}
assert "workdir" in seen["deps"], seen

# 2. 说明出现在 schemas 里
schemas = {item["name"]: item for item in capabilities.schemas()}
assert "echo_cap" in schemas and "bash" in schemas, schemas.keys()

# 3. 正常执行
out = capabilities.run([CapabilityInput("c1", "echo_cap", '{"text":"hi"}', {"text": "hi"})])
assert out[0].ok and out[0].content == "P:hi", out

# 4. 参数校验：缺必填
out = capabilities.run([CapabilityInput("c2", "echo_cap", "{}", {})])
assert not out[0].ok and "缺少必填参数" in out[0].content, out[0]

# 5. 参数校验：多余字段
out = capabilities.run([CapabilityInput("c3", "echo_cap", '{"text":"x","y":1}', {"text": "x", "y": 1})])
assert not out[0].ok and "不认识的参数" in out[0].content, out[0]

# 6. 停用 / 启用
assert capabilities.disable("echo_cap")
assert "echo_cap" not in {item["name"] for item in capabilities.schemas()}
out = capabilities.run([CapabilityInput("c4", "echo_cap", '{"text":"x"}', {"text": "x"})])
assert not out[0].ok and "已停用" in out[0].content, out[0]
assert capabilities.enable("echo_cap")

# 7. 注销（dispose 被调）
assert capabilities.unregister("echo_cap")
assert seen.get("disposed") is True
assert capabilities.registry.get("echo_cap") is None

# 8. 清单加载
manifest = tempfile.mktemp(suffix=".json")
with open(manifest, "w", encoding="utf-8") as file:
    json.dump({"capabilities": [
        {"module": "Capabilities.Bash", "class": "BashCapability"}
    ]}, file)
loaded = capabilities.load_manifest(manifest)
print("manifest loaded:", loaded)   # 重名会被跳过并上报，不算失败

# 9. 未知能力
out = capabilities.run([CapabilityInput("c5", "nope", "{}", {})])
assert not out[0].ok and "未知能力" in out[0].content, out[0]

print("CAPABILITY TEST OK")
