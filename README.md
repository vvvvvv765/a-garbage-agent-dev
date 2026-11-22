# Spirit —— Agent 计算机

> Agent 不是“一个会调工具的聊天机器人”，而是一台通用计算机 —— 只是坐在键盘前的人，从「人」换成了大模型。

Spirit 是一个把大模型当作**计算机使用者**的 Agent 运行时：调度核心、内存、上下文、能力体系、渲染、持久化各自是独立体系，由主板（Engine）装配起来。它自带 Web 工作台和 Electron 桌面壳，也支持在命令行里直接对话。

这是个人项目，仍在持续开发中；接口和行为会变。

---

## 设计前提

- **高强度承载**：按“长时间运行、高频轮次、长上下文、大批工具调用、外部状态会坏”来设计，而不是“演示能跑”。
- **有界 + 有降级**：所有随输入增长的结构都有上限，超限时有明确策略，并且可观测。
- **长跑可恢复**：轮内检查点、断流重试、缺结果显式标注，崩溃/取消后可以接着干。
- **能力优先**：默认不做保姆式限制；只挡会把机器搞坏的灾难操作。
- **一切皆能力**：能力 = 子体系，统一注册、统一审批、统一审计。

---

## 体系结构

| 体系 | 类比 | 职责 |
|---|---|---|
| AgentStart | BIOS | 自检、建立模型客户端 |
| DC / CPU | 处理器 | 单线程调度：状态、控制信号、循环 |
| Bus | 总线 | 体系之间交换资源的唯一通道（中立表） |
| Memory | 内存 | 按地址存记录；常驻 worker 并发接收 |
| Disk / Persist | 硬盘 | 会话、日志、产物、上传、沙箱的持久化 |
| GPU | 给模型看的 GPU | 上下文组装、清洗、预算、摘要 |
| Render | 给人看的 GPU | 流式正文、工具行、思考、异常 |
| Provider | 模型 I/O | Responses / Chat / Anthropic 三种方言适配、重连 |
| Capabilities | 外设簇 | bash、文件、网络、浏览器、数据处理等能力 |
| Scenarios | 场景包 | 提示词增量 + 能力白名单 + 安全默认值 |
| WebUI / Desktop | 前端 | Web 工作台 + Electron 桌面壳 |
| Faults / Log / Config | 报警器 / 记录仪 / 设置 | 异常处理、日志、配置 |
| MoBo / Engine | 主板 | 装配、开机、会话管理 |

详细设计见：

- [`spirit/说明/Agent项目构思.md`](spirit/说明/Agent项目构思.md) —— 设计思想与部件划分
- [`spirit/说明/项目体系说明.md`](spirit/说明/项目体系说明.md) —— 当前实现、边界与验证记录
- [`spirit/说明/体系总表.md`](spirit/说明/体系总表.md) —— 体系归属规则
- [`spirit/Scenarios/README.md`](spirit/Scenarios/README.md) —— 场景包格式

---

## 目录结构

```text
spirit/                 引擎（Python）
├─ AgentStart/          启动自检、模型客户端
├─ DC/                  调度核心、执行、安全、检查点
├─ Capabilities/        能力实现（bash、文件、网络、浏览器…）
├─ Scenarios/           场景包（daily / pentest）
├─ Prompts/             基础提示词
├─ WebUI/               Web 工作台（Flask + 静态资源）
├─ Memory/ GPU/ Disk/   内存、上下文、持久化
├─ Engine/ MoBo/        会话装配与主板
└─ 说明/                设计文档
desktop/                桌面壳（Electron + TypeScript）
tests/
├─ python/              100+ 个离线 Python 测试
└─ playwright/          Playwright / Electron UI 测试
```

---

## 快速开始

### 环境

- Python **3.11+**
- Node.js **20+**（只有桌面壳需要）
- 可选外部工具：ffuf、subfinder、dnsx、naabu、nuclei、gau、nmap（不随仓库分发）
- 可选浏览器外设：ego lite（Citro Labs 的 Chromium 浏览器，不随仓库分发，需自行安装并遵守其许可）

### 1. 引擎 + Web 工作台

```bash
cd spirit
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e .
```

复制配置模板并填入模型信息：

```bash
cp config.example.json config.json
```

```jsonc
{
  "llm": {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "api_key": "你的 Key",
    "model": "deepseek-Flash"
  }
}
```

> 也可以用环境变量：把 `llm.api_key` 留空，在 `llm.api_key_env` 写环境变量名（默认 `DEEPSEEK_API_KEY`）。

启动：

```bash
python -m MoBo.main web      # Web 工作台，默认 http://127.0.0.1:5000
python -m MoBo.main          # 命令行对话
```

### 2. 桌面壳（可选）

```bash
cd desktop
npm install
npm run start
```

桌面壳会拉起 `../spirit` 的引擎，数据落在 `desktop/data`，工作目录是 `desktop/workspace`。

---

## 能力与场景

所有场景共享的能力（`Scenarios/common.json`）：

`bash`、`readFile`、`writeFile`、`listDir`、`replaceInFile`、`searchFiles`、`viewImage`、`webSearch`、`browser`、`httpRequest`、`processStart` / `processOutput` / `processKill`、`todoWrite` / `todoRead`、`sessionSearch`、`parseData`、`archiveList` / `archiveExtract` / `archiveCreate`、`assetsWrite`

场景额外能力：

| 场景 | 额外能力 |
|---|---|
| **daily（日常）** | `dnsLookup`、`httpProbe`、`fetchUrl`、`findFiles`、`processList` |
| **pentest（渗透）** | `sandboxRun`、`fofaSearch`、`quakeSearch`、`hunterSearch`、`domainCollect`、`ffufScan`、`naabuScan`、`nucleiScan`、`gauUrls` |

场景 = 提示词增量 + 能力白名单 + 安全默认值；切换只在轮次边界生效。新增场景只需复制一个文件夹。

---

## 测试

```bash
# 离线 Python 测试（默认使用仓库内的 spirit/ 作为引擎根）
python tests/python/spirit_kernel_brutal_test.py

# UI 测试（需要先装 playwright）
npm install playwright
node tests/playwright/spirit_layout_ui.js
```

- Python 测试默认把 `tests/python` 的上两级 `spirit/` 当作引擎根，可用 `SPIRIT_SOURCE` 覆盖；虚拟环境解释器可用 `SPIRIT_PY` 覆盖。
- 带 `live` 字样的用例需要真实模型或 ego lite，会自行跳过。
- 详见 [`tests/README.md`](tests/README.md)。

---

## 安全声明

**Spirit 会在本机执行大模型生成的命令，默认不逐条确认。**

- 只在你拥有或已获得明确授权的环境中使用。
- 模型可能犯错，也可能被提示注入利用；运行前请确认工作范围与审批模式。
- `config.json` 里是明文 API Key，且被 `.gitignore` 排除；不要提交、不要外传。
- 本项目按 MIT 许可“按原样”提供，不对使用后果作任何担保。

---

## 已知限制

- 桌面壳与部分能力（bash、路径规则）以 Windows 为第一目标；引擎核心是跨平台的。
- 浏览器能力依赖外部的 ego lite，需自行安装；未安装时相关能力不可用。
- 外部工具、字典、nuclei 模板、便携 bash 均不随仓库分发，需要自行准备并遵守各自许可。
- 配置、会话、日志都是本地明文文件；不要在多用户机器上共享同一份数据目录。
- UI 测试依赖本机 Electron / Playwright 环境，部分用例以打包产物为对象。
- 项目仍是个人开发阶段，接口和行为可能变化。

---

## 第三方

- 供应商预设与部分交互行为参考 [cc-switch](https://github.com/farion1231/cc-switch)（MIT）
- Web UI 的 Markdown 解析使用 DeepSeek Harness 的 `marked.esm.js`（MIT，许可文件随附于 `WebUI/static/dsh/`）
- 其余依赖见 `spirit/pyproject.toml` 与 `desktop/package.json`

完整说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

---

## 许可

[MIT](LICENSE)
