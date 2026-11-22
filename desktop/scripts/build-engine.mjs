/** 用 PyInstaller 把引擎打成 onedir，供 electron-builder 塞进 resources/engine。 */
import { spawnSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const project = resolve(desktop, '..')
const engine = join(project, 'spirit')
const python =
  process.env.SPIRIT_PYTHON || join(project, '.venv', 'Scripts', 'python.exe')
const out = join(desktop, 'engine-dist')
const work = join(desktop, 'engine-build')

if (!existsSync(python)) {
  console.error(`找不到 Python：${python}\n可以设 SPIRIT_PYTHON 指向解释器`)
  process.exit(1)
}
if (!existsSync(join(engine, 'desktop_entry.py'))) {
  console.error(`找不到引擎入口：${join(engine, 'desktop_entry.py')}`)
  process.exit(1)
}

rmSync(out, { recursive: true, force: true })
rmSync(work, { recursive: true, force: true })

const args = [
  '-m', 'PyInstaller',
  '--noconfirm', '--clean', '--onedir', '--name', 'spirit-engine',
  '--distpath', out,
  '--workpath', work,
  '--specpath', work,
  '--add-data', join(engine, 'Prompts') + ';Prompts',
  '--add-data', join(engine, 'Scenarios') + ';Scenarios',
  '--add-data', join(engine, 'WebUI', 'static') + ';WebUI/static',
  '--collect-submodules', 'Capabilities',
  '--collect-submodules', 'Provider',
  '--collect-submodules', 'dns',
  '--collect-submodules', 'yaml',
  '--hidden-import', 'flask',
  '--hidden-import', 'openai',
  '--hidden-import', 'anthropic',
  '--hidden-import', 'regex',
  '--hidden-import', 'dns',
  '--hidden-import', 'yaml',
  'desktop_entry.py',
]

console.log(`[build-engine] ${python} ${args.join(' ')}`)
const result = spawnSync(python, args, { cwd: engine, stdio: 'inherit' })
if (result.status !== 0) {
  console.error(`[build-engine] 失败，退出码 ${result.status}`)
  process.exit(result.status ?? 1)
}
console.log(`[build-engine] 完成：${join(out, 'spirit-engine')}`)
