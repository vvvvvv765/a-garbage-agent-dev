/**
 * Spirit 桌面壳
 *
 * 职责只有三件：
 *   1. 首次启动建好 data / workspace，写默认 config.json
 *   2. 拉起引擎子进程（SPIRIT_HOME / SPIRIT_WORKDIR / SPIRIT_WEB_PORT）
 *   3. 开窗口加载引擎自带的页面
 *
 * 引擎本身不在这里；它只认接口，见 spirit/Engine/core.py。
 */
import { app, BrowserWindow, Menu, dialog, nativeTheme, shell } from 'electron'
import { spawn, type ChildProcess } from 'node:child_process'
import { cpSync, createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:net'
import { dirname, join, resolve } from 'node:path'

import { DEFAULT_CONFIG, WORKSPACE_FOLDERS, WORKSPACE_README } from './defaults'

const isDev = !app.isPackaged
const appRoot = (): string => (app.isPackaged ? dirname(app.getPath('exe')) : app.getAppPath())

/**
 * 数据一律跟着程序走（用户 2026-11-20 定）：安装版和便携版的 data / workspace
 * 都在 Spirit.exe 旁边。安装版早期版本把数据放在 %APPDATA%\\Spirit，
 * 首次启动时若发现旧位置有数据会**复制**过来（旧目录保留，不删）。
 */
const storageRoot = (): string => appRoot()
const dataDir = (): string => join(storageRoot(), 'data')
const workspaceDir = (): string => join(storageRoot(), 'workspace')

/** 早期安装版的默认 userData（%APPDATA%\Spirit），必须在 setPath 之前取。 */
const legacyUserData = (() => {
  try {
    return app.getPath('userData')
  } catch {
    return ''
  }
})()

/**
 * Chromium 的缓存 / 本地存储也塞进安装目录的 data\Electron；
 * 这样 %APPDATA% 下不再留任何 Spirit 数据。
 */
if (app.isPackaged) {
  try {
    const profile = join(dataDir(), 'Electron')
    mkdirSync(profile, { recursive: true })
    app.setPath('userData', profile)
  } catch (error) {
    console.error('set userData failed', error)
  }
}

function migrateOldStorage(): void {
  if (!app.isPackaged || !legacyUserData) return
  const oldRoot = legacyUserData
  for (const name of ['data', 'workspace']) {
    const oldPath = join(oldRoot, name)
    const newPath = join(storageRoot(), name)
    if (existsSync(newPath) || !existsSync(oldPath)) continue
    try {
      cpSync(oldPath, newPath, { recursive: true })
      log(`migrated ${name} from ${oldPath} -> ${newPath}`)
    } catch (error) {
      log(`migrate ${name} failed: ${String(error)}`)
    }
  }
}

let engine: ChildProcess | null = null
let win: BrowserWindow | null = null
let logStream: ReturnType<typeof createWriteStream> | null = null

function log(message: string): void {
  const line = `[${new Date().toISOString()}] ${message}`
  console.log(line)
  try {
    logStream?.write(line + '\n')
  } catch {
    /* 日志失败不拦主流程 */
  }
}

/** 首次启动的脚手架：目录 + 默认配置 + 工作区说明。 */
function ensureLayout(): void {
  migrateOldStorage()
  try {
    mkdirSync(dataDir(), { recursive: true })
    mkdirSync(join(dataDir(), 'Logs'), { recursive: true })
    mkdirSync(workspaceDir(), { recursive: true })
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'EPERM' || code === 'EACCES') {
      throw new Error(
        `安装目录不可写：${storageRoot()}\n\n`
        + 'Spirit 的所有数据（会话、配置、工作区、日志）都放在程序目录里。\n'
        + '请把 Spirit 安装到用户目录（例如 D:\\Spirit 或默认的 AppData 用户目录），'
        + '或给该安装目录写入权限。',
      )
    }
    throw error
  }

  const configPath = join(dataDir(), 'config.json')
  let config: any
  if (existsSync(configPath)) {
    try {
      config = JSON.parse(readFileSync(configPath, 'utf-8'))
    } catch {
      config = JSON.parse(JSON.stringify(DEFAULT_CONFIG))
    }
  } else {
    config = JSON.parse(JSON.stringify(DEFAULT_CONFIG))
  }

  config.engine = config.engine || {}
  // 旧桌面脚手架把 max_steps 默认写成 8，会把正常的多步任务在第 9 步掐断。
  // 高强度设计：不设人为步数上限（0），只靠停止 / 重复拦截 / 预算兜底。
  // 只迁移一次，之后用户自己改回 8 也尊重。
  if (config.engine.max_steps === 8 && !config.engine.max_steps_migrated) {
    config.engine.max_steps = 0
    config.engine.max_steps_migrated = true
    log('migrated engine.max_steps 8 -> 0 (no hard step cap)')
  }
  // 旧桌面脚手架默认把文件能力锁在工作区；沙箱应由模型自己决定是否用
  // 旧默认 4000 字符导致频繁 spill / 二次读文件；提高到 12000（只迁移旧默认值）
  if (config.engine.tool_output_inline === 4000
      && !config.engine.tool_output_inline_migrated) {
    config.engine.tool_output_inline = 12000
    config.engine.tool_output_inline_migrated = true
    log('migrated engine.tool_output_inline 4000 -> 12000')
  }
  if (config.engine.sandbox?.workspace_only === true
      && !config.engine.sandbox_workspace_migrated) {
    config.engine.sandbox.workspace_only = false
    config.engine.sandbox_workspace_migrated = true
    log('migrated engine.sandbox.workspace_only true -> false')
  }
  if (!config.engine.default_workspace) {
    config.engine.default_workspace = workspaceDir()
  }
  // 工作区目录被删 / 整个绿色目录被移动过：回到默认工作区
  const current = String(config.engine.workdir || '')
  if (!current || !existsSync(current)) {
    config.engine.workdir = workspaceDir()
  }
  writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n', 'utf-8')

  // 默认工作区才有目录约定；用户自己换到别的工作区不往那儿塞文件夹
  const configured = resolve(String(config.engine.workdir || ''))
  if (configured.toLowerCase() === resolve(workspaceDir()).toLowerCase()) {
    for (const folder of WORKSPACE_FOLDERS) {
      mkdirSync(join(workspaceDir(), folder), { recursive: true })
    }
  }

  const readme = join(workspaceDir(), 'README.md')
  if (!existsSync(readme)) {
    writeFileSync(readme, WORKSPACE_README, 'utf-8')
  }
}

function engineDir(): string {
  if (process.env.SPIRIT_ENGINE_DIR) return resolve(process.env.SPIRIT_ENGINE_DIR)
  return app.isPackaged
    ? join(process.resourcesPath, 'engine')
    : resolve(app.getAppPath(), '..', 'spirit')
}

function pythonFor(dir: string): string {
  if (process.env.SPIRIT_PYTHON) return process.env.SPIRIT_PYTHON
  const candidates = app.isPackaged
    ? [join(dir, 'python', 'python.exe')]
    : [join(dir, '..', '.venv', 'Scripts', 'python.exe')]
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate
  }
  return 'python'
}

function engineEntry(dir: string): { command: string; args: string[] } {
  const built = join(dir, 'spirit-engine.exe')
  if (existsSync(built)) return { command: built, args: ['web'] }
  return { command: pythonFor(dir), args: ['-m', 'MoBo.main', 'web'] }
}

function findPort(start: number): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const attempt = (port: number): void => {
      if (port > start + 50) {
        reject(new Error('找不到空闲端口'))
        return
      }
      const server = createServer()
      server.once('error', () => attempt(port + 1))
      server.once('listening', () => server.close(() => resolvePort(port)))
      server.listen(port, '127.0.0.1')
    }
    attempt(start)
  })
}

function buildLabel(): string {
  try {
    const info = JSON.parse(readFileSync(join(appRoot(), 'version.json'), 'utf-8'))
    return [
      info.app && `Spirit ${info.app}`,
      info.engine_commit && `主体 ${info.engine_commit}`,
      info.desktop_commit && `桌面壳 ${info.desktop_commit}`,
      info.built_at,
    ].filter(Boolean).join(' · ')
  } catch {
    return ''
  }
}

function startEngine(port: number): ChildProcess {
  const dir = engineDir()
  if (!existsSync(dir)) throw new Error(`找不到引擎目录：${dir}`)
  const entry = engineEntry(dir)

  const env = {
    ...process.env,
    SPIRIT_HOME: dataDir(),
    SPIRIT_WEB_HOST: '127.0.0.1',
    SPIRIT_WEB_PORT: String(port),
    SPIRIT_BUILD: buildLabel(),
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
  }

  log(`engine: ${entry.command} ${entry.args.join(' ')} (cwd=${dir})`)
  const child = spawn(entry.command, entry.args, {
    cwd: dir,
    env,
    windowsHide: true,
  })
  child.stdout?.on('data', (data) => log(`[engine] ${String(data).trimEnd()}`))
  child.stderr?.on('data', (data) => log(`[engine:err] ${String(data).trimEnd()}`))
  child.on('error', (error) => log(`engine spawn error: ${error.message}`))
  child.on('exit', (code, signal) => log(`engine exit code=${code} signal=${signal}`))
  return child
}

async function waitReady(port: number, timeoutMs = 30000): Promise<void> {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (engine && engine.exitCode !== null) {
      throw new Error(`引擎启动后退出了（code ${engine.exitCode}），看 data/Logs/desktop.log`)
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/status`, {
        signal: AbortSignal.timeout(1000),
      })
      if (response.ok) return
    } catch {
      /* 还没起来 */
    }
    await new Promise((done) => setTimeout(done, 300))
  }
  throw new Error('等待引擎就绪超时（30 秒），看 data/Logs/desktop.log')
}

function overlayColors(): { color: string; symbolColor: string; height: number } {
  return {
    color: nativeTheme.shouldUseDarkColors ? '#151517' : '#ffffff',
    symbolColor: nativeTheme.shouldUseDarkColors ? '#e6e6e8' : '#1f2328',
    height: 36,
  }
}

async function createWindow(port: number): Promise<void> {
  // 主题跟系统走：明确告诉 Electron 用操作系统设置，别沿用启动时缓存
  nativeTheme.themeSource = 'system'
  const themeBg = (): string => (
    nativeTheme.shouldUseDarkColors ? '#1d1c1a' : '#ffffff'
  )
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 640,
    show: false,
    title: 'Spirit',
    backgroundColor: themeBg(),
    icon: join(app.getAppPath(), 'assets', 'logo.png'),
    ...(process.platform === 'win32'
      ? { titleBarStyle: 'hidden' as const, titleBarOverlay: overlayColors() }
      : {}),
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  })

  const syncTheme = (): void => {
    if (!win) return
    const dark = nativeTheme.shouldUseDarkColors
    win.webContents.executeJavaScript(
      `window.dispatchEvent(new CustomEvent('spirit-system-theme', { detail: { dark: ${dark} } }))`,
    ).catch(() => {})
  }
  const syncOverlay = (): void => {
    if (!win) return
    win.setBackgroundColor(themeBg())
    if (process.platform === 'win32') win.setTitleBarOverlay(overlayColors())
    syncTheme()
  }
  nativeTheme.on('updated', syncOverlay)
  win.webContents.on('did-finish-load', syncTheme)

  win.once('ready-to-show', () => win?.show())
  win.on('closed', () => {
    nativeTheme.removeListener('updated', syncOverlay)
    win = null
  })

  const origin = `http://127.0.0.1:${port}`
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(origin)) shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(origin)) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })

  // 带版本号：旧缓存页 / 旧 static 混用会让界面缺按钮、事件绑不上
  const stamp = encodeURIComponent(buildLabel() || app.getVersion())
  await win.loadURL(`${origin}/?desktop=1&v=${stamp}`)
  log(`window loaded ${origin} (?desktop=1&v=${stamp})`)

  if (isDev && process.argv.includes('--dev')) {
    win.webContents.openDevTools({ mode: 'detach' })
  }
}

function stopEngine(): void {
  const child = engine
  engine = null
  if (!child || child.exitCode !== null) return
  log('stopping engine')
  try {
    if (process.platform === 'win32' && child.pid) {
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true })
    } else {
      child.kill('SIGTERM')
    }
  } catch (error) {
    log(`stop engine failed: ${String(error)}`)
  }
}

async function boot(): Promise<void> {
  ensureLayout()
  logStream = createWriteStream(join(dataDir(), 'Logs', 'desktop.log'), { flags: 'a' })
  log(`Spirit desktop start (dev=${isDev}, root=${appRoot()})`)

  Menu.setApplicationMenu(null)

  const port = await findPort(5000)
  engine = startEngine(port)
  await waitReady(port)
  await createWindow(port)
}

const locked = app.requestSingleInstanceLock()
if (!locked) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore()
      win.show()
      win.focus()
    }
  })

  app.whenReady().then(boot).catch((error: Error) => {
    log(`boot failed: ${error.message}`)
    dialog.showErrorBox(
      'Spirit 启动失败',
      `${error.message}\n\n日志：${join(dataDir(), 'Logs', 'desktop.log')}`,
    )
    app.quit()
  })

  app.on('before-quit', stopEngine)
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })
}
