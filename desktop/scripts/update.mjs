/**
 * 更新系统（开发机自更新）：
 *   1. 可选 git pull（两个仓库，没有远程就跳过）
 *   2. tsc 编译桌面壳
 *   3. PyInstaller 重打引擎
 *   4. 重新组装 release/Spirit（保留 data / workspace）
 *   5. 可选重新启动
 *
 * 用法：
 *   node scripts/update.mjs [--pull] [--relaunch] [--force] [--fresh]
 */
import { spawn, spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const project = resolve(desktop, '..')
const engine = join(project, 'spirit')
const release = join(desktop, 'release', 'Spirit')
const exe = join(release, 'Spirit.exe')

const flags = new Set(process.argv.slice(2))
const pull = flags.has('--pull')
const relaunch = flags.has('--relaunch')
const force = flags.has('--force')
const fresh = flags.has('--fresh')

function run(command, args, options = {}) {
  console.log(`\n[update] ${command} ${args.join(' ')}`)
  const result = spawnSync(command, args, { stdio: 'inherit', ...options })
  if (result.status !== 0) {
    throw new Error(`${command} 失败（退出码 ${result.status}）`)
  }
}

function isRunning() {
  if (process.platform !== 'win32') return false
  const result = spawnSync('tasklist', ['/FI', 'IMAGENAME eq Spirit.exe', '/NH'], {
    encoding: 'utf8',
  })
  return String(result.stdout || '').toLowerCase().includes('spirit.exe')
}

function stopApp() {
  console.log('[update] 关闭正在运行的 Spirit…')
  spawnSync('taskkill', ['/IM', 'Spirit.exe', '/F'], { stdio: 'ignore' })
  spawnSync('taskkill', ['/IM', 'spirit-engine.exe', '/F'], { stdio: 'ignore' })
}

function hasRemote(dir) {
  const result = spawnSync('git', ['remote'], { cwd: dir, encoding: 'utf8' })
  return String(result.stdout || '').trim().length > 0
}

function gitPull(dir, label) {
  if (!hasRemote(dir)) {
    console.log(`[update] ${label} 没有远程仓库，跳过 pull`)
    return
  }
  console.log(`\n[update] ${label} git pull`)
  const result = spawnSync('git', ['pull', '--ff-only'], { cwd: dir, stdio: 'inherit' })
  if (result.status !== 0) {
    console.warn(`[update] ${label} pull 失败，继续用本地代码`)
  }
}

function versionInfo() {
  try {
    return JSON.parse(readFileSync(join(release, 'version.json'), 'utf8'))
  } catch {
    return null
  }
}

try {
  if (isRunning()) {
    if (!force) {
      console.error('\n[update] Spirit 正在运行。关掉后再更新；或者加 --force 自动关。')
      process.exit(1)
    }
    stopApp()
  }

  if (pull) {
    gitPull(engine, '引擎')
    gitPull(desktop, '桌面壳')
  }

  run(process.execPath, [join(desktop, 'node_modules', 'typescript', 'bin', 'tsc')], {
    cwd: desktop,
  })
  run(process.execPath, [join(desktop, 'scripts', 'build-engine.mjs')], { cwd: desktop })
  run(
    process.execPath,
    [join(desktop, 'scripts', 'make-portable.mjs'), ...(fresh ? ['--fresh'] : [])],
    { cwd: desktop },
  )

  const info = versionInfo()
  console.log('\n[update] 更新完成')
  if (info) {
    console.log(`         版本 ${info.app} · 引擎 ${info.engine}`)
    console.log(`         引擎提交 ${info.engine_commit || '—'} · 桌面提交 ${info.desktop_commit || '—'}`)
  }
  console.log(`         位置：${exe}`)

  if (relaunch && existsSync(exe)) {
    console.log('[update] 启动新版本…')
    spawn(exe, [], { cwd: release, detached: true, stdio: 'ignore' }).unref()
  }
} catch (error) {
  console.error(`\n[update] 失败：${error.message}`)
  process.exit(1)
}
