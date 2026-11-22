# 第三方许可与资源说明

本项目以 MIT 许可发布（见 `LICENSE`）。以下内容来自第三方，或需要在分发时单独遵守其许可。

## 代码与参考实现

### DeepSeek Harness

- 使用范围：`spirit/WebUI/static/dsh/marked.esm.js`（Markdown 解析）。
- 许可：MIT，许可文件随附于 `spirit/WebUI/static/dsh/LICENSE`，分发时保留。
- 说明：对话与工具界面的 CSS 主题为 Spirit 自有样式，不再加载 DSH 的 `theme.css` / `vendor.css` / `app.css`。

### cc-switch

- 项目：https://github.com/farion1231/cc-switch
- 使用范围：供应商预设（地址、协议、认证方式、模型清单）、分类与卡片布局、供应商图标，以及连通性测试 / 测速 / 余额模板 / 故障转移等行为参考。Spirit 侧按自身架构用 Python 重写。
- 许可：MIT（完整许可文本见 `spirit/说明/第三方许可.md`）。

## 未随仓库分发的第三方组件

以下组件**不在本仓库中**，需要使用者自行获取，并遵守其各自的许可：

| 组件 | 用途 | 说明 |
|---|---|---|
| ego lite | 浏览器能力（`browser`） | Citro Labs 的 Chromium 浏览器；安装位置由 `engine.ego_browser` 或自动查找决定 |
| PortableGit / bash | 便携运行环境 | 打包时按需附带，源码仓库不含 |
| ffuf / subfinder / dnsx / naabu / nuclei / gau / nmap | 渗透场景能力 | 由 `tools.*` 配置路径；各自许可 |
| 字典、Nuclei 模板 | 扫描与爆破 | 不随仓库分发；请从各自来源获取并确认许可 |
| deepseek-harness 之外的字体与图标 | Web UI 静态资源 | 如需替换请注意溯源与授权 |

## Python / Node 依赖

Python 依赖见 `spirit/pyproject.toml`，Node 依赖见 `desktop/package.json` 与 `package-lock.json`。安装时各自携带其许可。
