/**
 * 零下载拼绿色目录（不需要 electron-builder）：
 *
 *   release/Spirit/
 *   ├─ Spirit.exe            ← 由 Electron 运行时改名
 *   ├─ *.dll / *.pak ...     ← Electron 运行时
 *   ├─ resources/
 *   │  ├─ app/               ← 桌面壳（dist + assets + package.json）
 *   │  └─ engine/            ← PyInstaller 打出的引擎
 *   ├─ data/                 ← 实例数据（更新时保留）
 *   ├─ workspace/            ← 默认工作区（更新时保留）
 *   └─ version.json          ← 构建信息
 *
 * 默认保留旧版的 data / workspace；--fresh 清空重来；--publish 不带 data / workspace（对外发布用）。
 */
import { execSync } from 'node:child_process'
import {
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const project = resolve(desktop, '..')
const engine = join(project, 'spirit')
const electronDist = join(desktop, 'node_modules', 'electron', 'dist')
const engineSrc = join(desktop, 'engine-dist', 'spirit-engine')
const releaseRoot = join(desktop, 'release')
const release = join(releaseRoot, 'Spirit')
const staging = join(releaseRoot, '.Spirit-new')
const backup = join(releaseRoot, '.Spirit-old')
const fresh = process.argv.includes('--fresh')
// --publish：做「发给别人」的包 —— 不带 data / workspace（免得把 Key 和会话发出去）
const publish = process.argv.includes('--publish')

if (!existsSync(join(electronDist, 'electron.exe'))) {
  console.error('找不到 Electron 运行时，先 npm install')
  process.exit(1)
}
if (!existsSync(join(engineSrc, 'spirit-engine.exe'))) {
  console.error('找不到引擎产物，先 npm run build:engine')
  process.exit(1)
}
if (!existsSync(join(desktop, 'dist', 'main.js'))) {
  console.error('找不到壳产物，先 npm run build')
  process.exit(1)
}

function gitHash(dir) {
  try {
    return execSync('git rev-parse --short HEAD', { cwd: dir, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function engineVersion() {
  try {
    const pyproject = readFileSync(join(engine, 'pyproject.toml'), 'utf8')
    return pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1] || ''
  } catch {
    return ''
  }
}

const pkg = JSON.parse(readFileSync(join(desktop, 'package.json'), 'utf8'))
const info = {
  app: pkg.version,
  engine: engineVersion(),
  built_at: new Date().toLocaleString('zh-CN', { hour12: false }),
  engine_commit: gitHash(engine),
  desktop_commit: gitHash(desktop),
}

rmSync(staging, { recursive: true, force: true })
mkdirSync(staging, { recursive: true })
const resources = join(staging, 'resources')

console.log('[portable] 拷 Electron 运行时…')
cpSync(electronDist, staging, { recursive: true })
renameSync(join(staging, 'electron.exe'), join(staging, 'Spirit.exe'))
rmSync(join(resources, 'default_app.asar'), { force: true })

console.log('[portable] 装桌面壳…')
const appDir = join(resources, 'app')
mkdirSync(appDir, { recursive: true })
cpSync(join(desktop, 'dist'), join(appDir, 'dist'), { recursive: true })
cpSync(join(desktop, 'assets'), join(appDir, 'assets'), { recursive: true })
writeFileSync(
  join(appDir, 'package.json'),
  JSON.stringify(
    {
      name: pkg.name,
      version: pkg.version,
      description: pkg.description,
      main: 'dist/main.js',
    },
    null,
    2,
  ) + '\n',
  'utf8',
)

console.log('[portable] 装引擎…')
cpSync(engineSrc, join(resources, 'engine'), { recursive: true })

// 绿色版自带 bash（PyInstaller 默认不打包 shell/PortableGit）
const shellSrc = join(engine, 'shell', 'PortableGit')
const shellDst = join(resources, 'engine', '_internal', 'shell', 'PortableGit')
if (existsSync(shellSrc)) {
  console.log('[portable] 装 bash（PortableGit）…')
  cpSync(shellSrc, shellDst, { recursive: true })
} else {
  console.warn('[portable] 没找到 spirit/shell/PortableGit，绿色版将没有内置 bash')
}

// 绿色版自带 ego lite（浏览器外设）：换机器没装 ego 时也能用
const egoSrc = join(engine, 'shell', 'ego-lite')
const egoDst = join(resources, 'engine', '_internal', 'shell', 'ego-lite')
const hasEgo = existsSync(egoSrc) && (
  existsSync(join(egoSrc, 'ego-browser.exe'))
  || readdirSync(egoSrc).some((name) => existsSync(join(egoSrc, name, 'ego-browser.exe')))
)
if (hasEgo) {
  console.log('[portable] 装 ego lite（浏览器）…')
  cpSync(egoSrc, egoDst, { recursive: true })
} else {
  console.warn('[portable] 没找到 spirit/shell/ego-lite，绿色版将依赖系统安装的 ego lite')
}

// 绿色版自带侦察工具 / 模板 / 字典（与安装包保持一致）
for (const name of ['tools', 'wordlists', 'nuclei-templates']) {
  const src = join(engine, 'shell', name)
  const dst = join(resources, 'engine', '_internal', 'shell', name)
  if (existsSync(src)) {
    console.log(`[portable] 装 ${name}…`)
    cpSync(src, dst, { recursive: true })
  }
}

if (publish) {
  console.log('[portable] 发布模式：不拷 data / workspace')
  mkdirSync(join(staging, 'data'), { recursive: true })
} else if (!fresh) {
  for (const name of ['data', 'workspace']) {
    const old = join(release, name)
    if (existsSync(old)) {
      console.log(`[portable] 保留 ${name}…`)
      cpSync(old, join(staging, name), { recursive: true })
    }
  }
  // 拷贝后自查：data/config.json 里有没有非空 Key（有就别把这个目录发出去）
  try {
    const cfgPath = join(staging, 'data', 'config.json')
    if (existsSync(cfgPath)) {
      const cfg = JSON.parse(readFileSync(cfgPath, 'utf8'))
      const keys = (cfg.llm?.providers || []).filter((p) => String(p.api_key || '').trim())
      if (String(cfg.llm?.api_key || '').trim()) keys.push({ name: 'llm.api_key' })
      if (keys.length) {
        console.warn('[portable] ⚠️ data/config.json 里有明文 Key —— 这个目录只能自己用，不要发给别人')
        console.warn('[portable]    要发布给别人用 `npm run publish`（会去掉 data / workspace）')
      }
    }
  } catch { /* 配置坏了不影响打包 */ }
}

writeFileSync(join(staging, 'version.json'), JSON.stringify(info, null, 2) + '\n', 'utf8')
writeFileSync(join(staging, 'portable.marker'), 'portable\n', 'utf8')
const feedback = join(desktop, '反馈说明.txt')
if (existsSync(feedback)) {
  cpSync(feedback, join(staging, '反馈说明.txt'))
}
writeFileSync(
  join(staging, '版本信息.txt'),
  [
    'Spirit',
    '',
    `版本：${info.app}（引擎 ${info.engine}）`,
    `构建：${info.built_at}`,
    `引擎提交：${info.engine_commit || '—'}`,
    `桌面提交：${info.desktop_commit || '—'}`,
    '',
    '双击 Spirit.exe 启动。',
    'data 里是配置 / 会话 / 日志，workspace 是默认工作目录；更新会保留这两个目录。',
    '模型和 Key 在「设置 → 模型」里填。',
    '',
  ].join('\r\n'),
  'utf8',
)

rmSync(backup, { recursive: true, force: true })
let movedOld = false
try {
  if (existsSync(release)) {
    renameSync(release, backup)
    movedOld = true
  }
  renameSync(staging, release)
} catch (error) {
  // 替换失败：把旧版本放回去，别让 release/Spirit 消失
  if (movedOld && !existsSync(release)) {
    try {
      renameSync(backup, release)
    } catch {
      /* 尽力恢复 */
    }
  }
  console.error('[portable] 替换失败——Spirit 可能还开着。关掉应用后重跑。')
  console.error(`[portable] ${error}`)
  process.exit(1)
}
rmSync(backup, { recursive: true, force: true })

console.log(`[portable] 完成：${release}`)
console.log(`[portable] ${info.app} · engine ${info.engine_commit || '—'} · desktop ${info.desktop_commit || '—'}`)
