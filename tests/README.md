# 测试

两类测试，互不依赖：

| 目录 | 内容 | 运行方式 |
|---|---|---|
| `python/` | 100+ 个离线测试（内核、能力、持久化、会话、沙箱、SSE、渲染…） | `python tests/python/<name>_test.py` |
| `playwright/` | UI / Electron / 打包产物测试 | `node tests/playwright/<name>.js` |

## Python 测试

- 引擎根默认解析为 **本仓库的 `spirit/`**（`tests/python` 上两级）。换位置时用环境变量覆盖：

  ```bash
  export SPIRIT_SOURCE=/path/to/spirit
  ```

- 测试会自己设置 `SPIRIT_HOME` / `SPIRIT_SESSION_DIR` / `SPIRIT_LOG_DIR` / `SPIRIT_WORKDIR` 到临时目录，不会污染本地数据。
- 带 `live` 字样的用例需要真实模型或 ego lite，缺少时会跳过或按文件内说明处理。
- 需要包含可选依赖（`dnspython`、`PyYAML` 等）时，先 `pip install -e ../spirit`。

## Playwright / Electron 测试

- 需要 `npm install playwright`，以及桌面壳依赖 `desktop/node_modules`。
- 引擎解释器可用 `SPIRIT_PY` 覆盖；Electron 可执行文件与打包产物的路径都按仓库相对位置解析。
- 截图默认写到运行目录下的 `tupian/`（已在 `.gitignore` 中忽略）。
- 部分用例面向 `desktop/release/Spirit` 打包产物，需要先 `npm run portable` 才会存在。

## 建议的本地顺序

1. 先跑几个核心离线测试：`spirit_kernel_brutal_test.py`、`spirit_boundary_test.py`、`spirit_multisession_test.py`
2. 再跑 UI：`spirit_layout_ui.js`、`spirit_thinking_ui.js`
3. 最后跑 live / packaged 用例（依赖外部工具与打包产物）
