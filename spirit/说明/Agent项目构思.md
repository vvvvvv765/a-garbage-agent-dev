# Agent 通用计算机 —— 项目构思

> 这份文档记录项目背后的**思想**与**当前实现**（2026-11-17）。
> 文中的引用来自讨论，保留原话。

---

## 一句话

**Agent 不是“一个会调工具的聊天机器人”，而是一台通用计算机——只是坐在键盘前的人，从“人”换成了大模型。**

---

## 〇、设计前提：高强度承载（2026-11-20 他定）

> 这台计算机**不是“演示能跑”的玩具**。它的预期使用强度很高：长时间连续运行、高频轮次、长上下文、大批工具调用、外部网关随时变异、工具结果不可信、配置和会话文件可能被手改坏。**所有设计都先按“会用很久、会被用狠”来推演。**

硬约束（写代码 / 评审时逐条自问）：

1. **有界 + 有降级**：任何随输入增长的结构（队列、deque、日志、会话、spill、上传区、内存）必须有上限；超限有明确策略（丢最旧 / 落盘 / 截断），**丢弃要可观测**，不静默。
2. **消费不能拖住生产**：慢消费者（渲染、SSE 慢客户端）只允许“跳过 / 淘汰”，不允许回放、反压或卡死主流程；流式游标必须按**绝对序**推进，不能靠容器长度。
3. **共享可变状态默认并发**：落盘水位、会话切换、配置读写、游标更新都在临界区内完成。“今天只有单线程调用”是现状，不是可以写进代码的假设。
4. **外部状态默认会坏**：配置字段类型、网关流（断流 / 乱序 / 末尾憋一坨）、会话 JSONL（坏行 / 半行）、工具结果——损坏时**降级运行并留痕**，不带崩整机。
5. **可观测**：每次模型调用都要能回答“慢在上游还是本机”（首段 / 末段 / 分段数）；每次降级、丢弃、拒绝都要留日志或指标。
6. **长跑可恢复**：崩溃、断流、取消之后能接着干；半截状态必须**显式标注**（缺结果、半句回复），不能当作完整历史。
7. **资源有轮转**：线程、worker 进程、日志、spill、上传区都有上限与清理策略；不允许无界增长。
8. **判据**：这段代码在「10 倍负载 / 连续跑 3 天 / 网关乱吐 / 配置被手改坏」的情况下会怎样？

**不推翻现有架构选择**：CPU 单线程 + 可推演仍然是资产。高强度靠**边界与降级**扛，不靠把 CPU 拆成并发。

### 能力优先，不过度限制（同一条前提的另一面，2026-11-20 他再强调）

> “**不要过度限制大模型**。”——用户是这台计算机的操作员，Spirit 的职责是让它**能干成事**，不是把它当需要看管的孩子。

- 闸只挡**会把机器搞坏**的灾难（分区 / 格式化 / 引导 / 机器数据 / 工作区根），**不做保姆**：读什么、去哪、用什么命令，默认放行；
- 审批 / 拦截 / 限制是**成本**，不是默认值——每加一条规则先问“它挡的是灾难，还是只是我觉得该挡”；
- 判据的反面同样成立：为了“安全”而让一个正常任务过不去、或者每次都弹卡，就是设计错误；
- 外部 AI 审计的建议按**参考**处理：它不知道这条前提，凡是以“更安全”为名的扩权式限制，先对照这一条再决定。

---

## 一、总纲：Agent = 通用计算机

> “agent是什么 其实就是大模型能干的事，这让我联想到了通用计算机，不就是把要干的事情放到同一个计算机上嘛，而Agent这里只是对象变了，从人变为了大模型，如果把大模型看作人，agent就是一台通用计算机。只不过现实中是人去控制大模型，大模型使用agent这台通用计算机。”

三层角色：

| 角色 | 是谁 |
|---|---|
| 最上层用户 | 人 |
| 操作员（计算机的使用者） | 大模型 |
| 机器 | Agent 计算机 |

> “我这里的定义是大模型是Agent计算机的使用者……（现实世界中同样还不是人输入的。只不过这里是 agent + 大模型。当然我不是说人就不参与了）”

### 一次纠正

> “上面你说大模型是CPU，这点不对，我这里的定义是大模型是Agent计算机的使用者，即我要以旧版的信号机制来建立一个Agent计算机中的CPU。”

所以：**大模型不是 CPU；CPU 是 Agent 计算机自己的调度核心**。

---

## 二、部件与插槽

> “我定义好每个硬件，最终哪一个主板都装上，可以。”

每个部件只暴露一个标准接口，由**主板（MoBo / Engine）**把它们接起来。

验收判据：**换掉一个部件，其他部件零改动。**

---

## 三、体系划分

> “信号机制像不像CPU，每次的打印像不像GPU的渲染（这里是给人看），上下文的管理是不是GPU即给大模型看的（这里排除人），这些工具像不像是该Agent通用计算机的其他能力。”

| 体系 | 类比 | 职责 |
|---|---|---|
| BIOS（AgentStart） | 主板固件 | 自检、建立客户端、产出 responses 句柄 |
| CPU（DC） | 处理器 | 只调度：状态、控制信号、循环 |
| 中立表（Bus） | 总线 | 体系之间交换信号 / 资源的唯一通道 |
| 内存（Memory） | 内存 | 按虚拟地址存数据；常驻 worker 并发接收 |
| 硬盘（Disk） | 硬盘 | 存储主体系：冷数据区域（工作区 / 能力产物 / 会话 / 日志 / 沙箱 / 上传）；**不可删除** |
| 上下文（Context） | 硬盘的会话 / 快照区域 | 会话落盘、恢复、有序快照 / 统计 |
| GPU 渲染 | 给模型看的 GPU | 加工 + 清洗 + 预算 + 摘要 → 中立消息包 |
| 渲染（Render） | 给人看的 GPU | 流式正文、工具行、结果、异常；控制台 / sink 两种出口 |
| Web UI（适配层） | 前端 | 单对话框；接 Render 的 sink + UserInput 的 source |
| 大模型 I/O（ModIO） | 处理器接口 | 请求、流解析、重连、摘要调用（适配层） |
| 工具体系（Tools） | 外设簇 | 工具 = 子体系；注册、执行、spill、写内存 |
| 用户输入（UserInput） | 输入设备 | 读输入、写内存、向 CPU 报告 |
| 异常处理（Faults） | 报警器 | 每体系一个 handler；异常写内存 + 渲染 + 日志 |
| 日志（Log） | 记录仪 | 运行事件写 `Logs/spirit.log` |
| 配置（Config） | 设置 | `config.json`，各体系按需读 |
| 主板（MoBo / Engine） | 主板 | 装配、开机 |

---

## 四、控制流 / 数据流 / 辅助流

> “CPU只负责调度，每个模块处理自己的数据……我觉得CPU只负责发送信号。”

> “每个模块要设计对CPU的回显。”

三条流分开：

| 流 | 方向 | 载体 |
|---|---|---|
| **控制** | CPU → 体系 | 总线上的 `Contract` 控制对象（只有 CPU 写） |
| **报告** | 体系 → CPU | 总线上的 `Contract` 报告对象（体系写） |
| **数据** | 生产者 → 内存 → GPU | 内存虚拟地址，不经 CPU 搬运 |

> “我觉得运输的逻辑不在于这个数据是否运输到该模块，而是该模块是否开始处理该数据。”

**运输 = 处理权的转移**：数据在共享对象里不动，动的是“该谁开始处理”。

> “体系之间可以相互辅助，但即使是辅助，也要通过 CPU 的调度。”

辅助能力由 CPU 在启动时注入（例如 GPU 的摘要能力 = `modi.summarize`），体系之间不直接调用。

---

## 五、内存、上下文、GPU

> “先把收集到的上下文放到内存，再把内存中的上下文数据加工，把加工完的上下文发给大模型。内存可以建立几个虚拟内存，每个虚拟内存存的不一样，一个存工具调用，一个存思考。”

### 内存（Memory）

- 一条**全局有序日志**作为真源：每条记录一个自增 `seq`
- **虚拟地址**：`user` / `assistant` / `tool_call` / `tool_output` / `reasoning` / `exception` / `summary`
- 视图 = 按地址过滤
- **常驻 worker**：任意线程 `submit` → FIFO 队列 → worker 单写（顺序 = 队列顺序）

### 上下文（Context）

- 落盘：新记录追加到 JSONL（只追加）
- 恢复：`load`（启动阶段用）
- 辅助：`ordered()` 有序快照、`stats()`
- **不负责加工 / 清洗**

### 硬盘（Disk）

- 与内存分工：内存 = 当前要进上下文的热数据；硬盘 = 冷数据，模型用能力按需读
- 区域（每个区域 = 磁盘上一个文件夹）：`workspace`（工作区，子体系）、`artifacts`（**能力产物区，工作区之外**）、`sessions`、`logs`、`sandbox`、`uploads`
- 大输出规则：能力结果超过 inline 阈值 → 写进 **`数据根/Artifacts/spill/`（能力产物区，不在工作区）**，返回摘要 + 路径；模型需要时 `readFile`。**工作区只放作业文件，框架产物不混进去**（2026-11-20 他定）
- **主体系之一，不可删除**：没有注销入口；UI 只提供看用量 / 打开文件夹 / 清能力产物 / 删会话
- **内存只驻留热记录（2026-11-20 批 AF）**：最新摘要的 `end_seq` 是冷热边界——之前不再进上下文的原始记录从内存退役（磁盘不动），摘要 / 用量 / 待办留在视图；启动只铺热记录，回放要更早时从磁盘按需读。内存上界 ≈ 可见窗口 + 摘要 + 常量

### GPU 渲染（给大模型）

流水线：

```text
取快照 → 视图（摘要遮蔽）→ 选地址 → 配对修复 → 归范
→ 预算（剪旧工具结果）→ 摘要压缩 → 组装 → 加前缀 → 冻结
```

- **选**：`user` / `assistant` / `tool_call` / `tool_output`；`reasoning` 看开关；`exception` 不送
- **配对修复**：孤立结果丢；缺失结果末尾补；全部调用在前、结果在后
- **预算**：估算 token → 先剪旧工具结果（保留最近 N，带落盘路径）
- **摘要压缩**：剪完仍超 → 摘要最旧若干轮（保留最近 K 轮原文），存 `summary` 记录并遮蔽 `[1, end_seq]`；**原记录不删**
- **前缀**：稳定 `system_prompt` 走 `instructions`；项目上下文作为一条消息
- **冻结**：输出 `ContextBundle(instructions, messages, meta)`，消息元组不可变

> “输出体系要专门建立一个渲染体系，用于渲染给用户看，而上下文体系就相当于给大模型看的，是Agent计算机中的GPU。”

两个“显示”：渲染体系给人看；GPU 渲染体系给模型看。

---

## 六、工具体系

> ⚠️ **2026-11-18：工具体系改名为「能力体系」**（代码在 `Capabilities/`，每个工具 = 一个能力 = 它的子体系）。
> 下面关于工具接口的设计仍然适用；注册表 / 启停 / 配置 / 依赖注入见 `项目体系说明` §二。

> “每个工具都是该工具体系的子体系……工具的输出（到内存）工具体系可以自行加工。”

工具作者只写两个方法：

```python
class Tool(Protocol):
    def spec(self) -> ToolSpec: ...
    def run(self, arguments: dict) -> str: ...
```

三个接口对象：

| 对象 | 作用 |
|---|---|
| `ToolSpec` | 工具说明（name / description / parameters） |
| `ToolInput` | 模型对工具的输入（call_id / name / raw_arguments / arguments） |
| `ToolOutput` | 工具对模型的输出（content / ok / meta；`to_record()` 写内存） |

`ToolSystem` 负责：注册 / `schemas()` / 执行（线程池）/ 后处理（归一化、超限 **spill 落盘**）/ 写内存 `tool_output`。

数据路径：

```text
ModO 解析 function_call → 内存 tool_call
  → CPU 调度 ToolSystem.run(ToolInput)
  → 工具子体系执行 → 后处理 → 内存 tool_output
  → GPU 下一轮选中 → 送模型
```

---

## 七、大模型 I/O、适配、思考

### 适配接口

`ModIO/Adapter.py`：

- `LLMAdapter`（Protocol）：请求构造 + 事件词汇 + 条目转换
- `ResponsesAdapter`：当前 OpenAI Responses API（DeepSeek `/responses` 兼容）
- `get_adapter(provider)`：以后接 Anthropic 等，新增一个类即可

### 重连

- 可重试：网络 / 超时 / 限流 / 5xx / 流中断
- 不可重试：鉴权 / 无权限 / 参数 / 不存在
- 指数退避，最多 5 次；放弃 → 报错给 CPU，进入下一轮不崩

### 思考（reasoning）

- 开关由 **CPU 统一调度**：`engine.thinking` / `DC.set_thinking()`；**只在轮次边界生效**
- 强度同属控制：总线 `CPU_THINKING` 是 `ThinkingControl(should_process, effort)`；适配层把 effort 翻成 provider 参数（DeepSeek：`low` / `medium` / `high`；关闭时发 `none`）
- 存储：`response.completed.output` 里的完整 reasoning 块（不是 delta 文本）
- 回传：开关打开时按 `seq` 原样放回 `input`；关闭时不送
- DeepSeek 实测：支持 `none/low/medium/high`；条目含 `encrypted_content`；工具循环回传通过
- 注意：简单问题模型可能不产生 reasoning（effort 是提示，不是保证）

---

## 八、Web UI（渲染 + 三个控件）

- 运行：`cd spirit && python -m WebUI.server` → `http://127.0.0.1:5000`
- 界面只有：**渲染区 + 一个输入框 + 思考开关 + 思考强度**；没有顶栏 / 状态栏 / 侧边栏 / 设置页 / 插件市场
- 接线：
  - `Render.set_console(False)` + `Render.add_sink(...)` → 事件队列 → SSE `/api/events`
  - `UserInput.set_source(...)` → 输入队列 → `POST /api/send`
  - 思考开关 / 强度 → `POST /api/settings` → `Engine.set_thinking()` → 下一轮开始生效
  - 刷新页面 → `GET /api/history` → `Render.history(内存记录)` → 用同一套显示事件回放（用户 / 正文 / 工具 / 异常；思考、摘要不回放）
  - Spirit 在后台线程跑，浏览器只负责收发
- 用户渲染采用 Spirit 自有视觉主题；交互参考终端 Agent 的简洁活动展示，但不复用 Claude Code 专属源码或品牌素材。旧 DSH CSS 已不再加载，Markdown 解析器许可单独记录。
- 配置：`engine.web_host` / `engine.web_port`

## 九、异常 / 日志 / 配置

- **异常**：每个体系一个 handler → 写内存 `exception` + 渲染体系显示 + 日志 `ERROR`；异常不送模型
- **日志**：`Logs/spirit.log`（运行事件）；`Session_Storage/*.jsonl`（对话记录）
- **配置**：`spirit/config.json`
  - `llm`：provider / model / base_url / api_key_env / reasoning / context_window
  - `engine`：max_steps（0 = 不限） / thinking / system_prompt / project_context / tool_output_inline / keep_recent_tool_results / summarize / keep_recent_turns / tool_workers / spill_dir / budget_ratio / bash_path

---

## 十、并发模型

| 体系 | 并发形态 |
|---|---|
| 默认会话 CPU / BIOS / UserInput / ModIO / GPU / Context / Render | CPU 主线程，顺序 |
| **额外会话（K4b）** | 每会话一套独立 CPU 线程 + Memory / 总线 / Render / GPU / Persist |
| **Memory** | 常驻 worker（1）+ FIFO 队列（每会话一套） |
| **Tools** | 线程池（默认 4，跨会话共享；执行记录按 session 标记） |

规则：工具 worker 只返回值，不写共享对象；共享数据由 CPU 线程统一提交；内存 worker 是唯一写者。

---

## 十一、启动顺序

```text
MoBo / Engine
  1. BIOS Create：读 key → 建客户端 → 句柄自己进表 + 报告 SI
  2. 恢复最新会话（Context.restore_latest，配置 engine.restore；内存非空则跳过）
  3. 工具体系上总线（keys.TOOLS）
  4. CPU boot：注册 CPU_USER / CPU_MOD / CPU_THINKING；注入 summarizer；检查 BIOS 报告
  5. CPU run：进入主循环
```

**import 不是启动**：模块只定义，活由主板按顺序调。

---

## 十二、当前实现（2026-11-17）

> ⚠️ **2026-11-18 已按 [体系总表](体系总表.md) 改造**：`Context/`、`ModIO/` 已拆掉，
> 文件与职责的最新对照见 [项目体系说明](项目体系说明.md) §二。下表保留为 11-17 的实现快照。

| 思想 | 文件 |
|---|---|
| BIOS | `AgentStart/Agentstart.py` |
| CPU | `DC/CPU.py` |
| 总线 / 地址 | `Bus/NeutralTable.py`、`Bus/keys.py` |
| 协议 | `Contract/base.py` |
| 内存 | `Memory/Memory.py`、`Memory/Addresses.py` |
| 上下文 | `Context/Context.py` |
| GPU | `GPU/core.py` |
| 渲染（给人） | `Render/Render.py` |
| 大模型 I/O | `ModIO/ModI.py`、`ModIO/ModO.py` |
| 适配接口 | `ModIO/Adapter.py` |
| 重连 | `ModIO/Reconnect.py` |
| 工具体系 | `Tools/System.py`、`Tools/Spec.py`、`Tools/Input.py`、`Tools/Output.py`、`Tools/BashTool.py` |
| 用户输入 | `UserInput/Input.py` |
| 异常 | `Faults/core.py` |
| 日志 | `Log/core.py` |
| 配置 | `Config/core.py`、`config.json` |
| 主板 | `MoBo/main.py`（入口）→ `Engine/core.py`（门面） |
| Web UI | `WebUI/server.py`、`WebUI/static/` |
| 运行环境 | `shell/PortableGit`（可被 `engine.bash_path` 覆盖） |

### 已验证

- 流式对话、上下文维护、`exit` / EOF、空输入跳过
- bash 工具调用闭环、多轮工具、**一个响应多个工具调用**
- 工具输出超限 **spill 落盘**、工具调用可见
- 内存并发：4 线程 200 条，`seq` 有序
- GPU：配对修复、空 assistant 丢弃、孤立结果丢弃、缺失结果补齐
- 预算：剪旧工具结果（保留最近 N，带落盘路径）
- **摘要压缩**：假摘要、真摘要调用、持久化恢复均验证
- **思考**：真实 API 联调通过（effort / 完整块 / 工具循环回传）
- 重连：分类、退避、放弃不崩
- 异常：上报 → 内存 → 渲染 → 日志；每轮异常不崩
- 日志 / 配置 / 工具接口 / 全流程回归
- 统一入口：`MoBo → Engine.start()`；`shell/` 已迁入 `spirit/`（`engine.bash_path` 可覆盖）；`Signal/` 死代码已移除
- **Web UI**：单对话框端到端通过（GET / 200、发送、SSE 流式 `assistant_delta` / `assistant_end`）
- **会话恢复**：跨进程实测——第二次启动后 `/api/history` 还原上一次对话，模型也能答出上一轮内容（暗号「蓝鲸」✓）

### 还没做

- 新建 / 切换会话的入口（现在启动总是续最新一份 `session-*.jsonl`）
- 新 provider 的 Adapter（接口已留；Anthropic thinking 块 + signature 待补）
- 更多工具（插槽已留）

---

## 十三、设计判据

1. 体系之间零 import，只依赖中立包；辅助经 CPU 调度
2. 一个 key 一个写者
3. 数据直写内存，控制走信号 / 返回值
4. 启动期只登记，运行期只读
5. 第二个样本才抽象
6. 换部件零改动
7. 压缩 = 视图遮蔽，不删原始数据
