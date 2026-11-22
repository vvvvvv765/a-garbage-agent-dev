# 场景包

一个场景 = 一个文件夹：

```text
Scenarios/<id>/
├─ scenario.json   # 名称 / 描述 / 能力子集 / 安全默认值
└─ prompt.md       # 叠加在 Spirit 提示词后面的场景提示词
```

`scenario.json`：

```json
{
  "id": "daily",
  "name": "日常",
  "description": "通用对话、代码、文件与资料检索",
  "prompt": "prompt.md",
  "capabilities": ["bash", "readFile"],
  "defaults": {
    "approval": "rules",
    "max_steps": 0,
    "sandbox": {"workspace_only": true}
  }
}
```

- `capabilities` 是**白名单**：没列出的能力在切换到这个场景时会被停用
- `defaults` 在切换时写入配置：`sandbox.*` 写到 `engine.sandbox.*`，其余写到 `engine.*`
- 场景提示词是**增量**，Spirit 的 `Prompts/engine.md` 仍然是底座，不复制整份
- 切换只在轮次边界生效；Spirit 正在处理一轮时会拒绝
- 新增场景：复制一个文件夹，改 `scenario.json` 和 `prompt.md`，重启或切换即可
