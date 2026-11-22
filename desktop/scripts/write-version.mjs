/** 生成安装包用的 version.json（放在安装目录根，启动时「关于」显示）。 */
import { execSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const desktop = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const project = resolve(desktop, '..')
const engine = join(project, 'spirit')

function gitHash(dir) {
  try {
    return execSync('git rev-parse --short HEAD', { cwd: dir, encoding: 'utf8' }).trim()
  } catch {
    return ''
  }
}

function engineVersion() {
  try {
    const text = readFileSync(join(engine, 'pyproject.toml'), 'utf8')
    return text.match(/^version\s*=\s*"([^"]+)"/m)?.[1] || ''
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
writeFileSync(join(desktop, 'version.json'), JSON.stringify(info, null, 2) + '\n', 'utf8')
console.log('[version]', JSON.stringify(info))
