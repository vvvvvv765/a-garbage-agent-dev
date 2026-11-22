# Spirit 桌面壳

Electron + TypeScript。只做三件事：

1. 首次启动建 `data/`、`workspace/`，写默认 `config.json`
2. 拉起引擎子进程（`SPIRIT_HOME` / `SPIRIT_WORKDIR` / `SPIRIT_WEB_PORT`）
3. 开窗口加载引擎自带的 Spirit 工作台页面

引擎源码在 `../spirit`，这里不碰引擎内部。

## 开发

```bat
npm install
npm run start      :: 编译 + 开窗口
npm run dev        :: 编译 + 开窗口 + DevTools
```

开发模式用 `../.venv` 的 Python 跑引擎源码，数据落在本目录的 `data/`、`workspace/`。

## 组装 Spirit 目录

```bat
npm run portable        :: 重打引擎（PyInstaller）+ 组装
npm run portable:fast   :: 引擎没改时只重组
```

产物：

```text
release\Spirit\
├─ Spirit.exe
├─ resources\
│  ├─ app\      桌面壳
│  └─ engine\   引擎（onedir，含 Python 运行时）
├─ data\        首次启动生成
└─ workspace\   首次启动生成
```

双击 `Spirit.exe` 即用，不需要装 Python。第一次启动会生成 `data/config.json`；模型 / Key 在界面「设置 → 模型」里填，写进 `data/config.json`（也兼容环境变量 `DEEPSEEK_API_KEY`）。

## 更新

开发机（代码改了之后）：

```bat
更新.bat            :: git pull（有远程才拉）→ 编译壳 → 重打引擎 → 重组
更新并启动.bat      :: 同上，完成后自动启动
```

或命令行：

```bat
npm run update
npm run update:relaunch
```

- **保留 `data/` 和 `workspace/`**：会话、配置、Key、工作区文件都不动，只换程序
- Spirit 正在运行时更新会拒绝；加 `--force` 自动关掉再更新
- `--fresh` 清空 `data/` / `workspace/` 重装（慎用）
- 每次构建写 `release/Spirit/version.json`（版本 / 构建时间 / 两个仓库的提交号），菜单「关于 Spirit」会显示
- 以后有了远程仓库，`--pull` 会自动拉最新代码；现在没有远程就跳过

## 默认工作区

首次启动会在 `workspace/` 下建好目录约定，模型按类型归位：

```text
workspace\
├─ scripts\   模型写的脚本（.py / .sh / .ps1）
├─ files\     文档、数据、报告、下载的文件
├─ images\    图片
├─ videos\    视频
├─ audio\     音频
└─ tmp\       临时文件，可随时清
```

用户把工作区换到别处时，不会往那个目录硬塞文件夹。

## 可调环境变量

| 变量 | 作用 |
|---|---|
| `DEEPSEEK_API_KEY` | 模型 Key（可选；界面里填了就写进 `data/config.json`） |
| `SPIRIT_ENGINE_DIR` | 开发模式下指定引擎源码目录 |
| `SPIRIT_PYTHON` | 指定 Python 解释器 |

## 备注

- `Spirit.exe` 未签名，Windows SmartScreen 可能弹提示（“仍要运行”）。
- Spirit 目录可整体拷走；`data/` 里是会话和日志，别随便外发。
- 换引擎版本：更新 `../spirit` 后跑 `npm run portable`，`data/` 和 `workspace/` 不受影响。
