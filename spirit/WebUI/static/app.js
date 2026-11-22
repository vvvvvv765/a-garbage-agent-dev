/* Spirit Web UI —— 独立呈现层
   数据来自引擎 SSE（/api/events）；视觉与交互由 Spirit 自有主题负责。 */

import { marked } from './dsh/marked.esm.js'
import { PROVIDER_CATEGORIES, PROVIDER_PRESETS } from './provider-presets.js'

/* ---------- 元素 ---------- */
const shell = document.getElementById('shell')
const mobileSidebarQuery = window.matchMedia('(max-width: 640px)')
const syncSidebarToViewport = (query = mobileSidebarQuery) => {
  shell.classList.toggle('collapsed', query.matches)
}
syncSidebarToViewport()
if (mobileSidebarQuery.addEventListener) {
  mobileSidebarQuery.addEventListener('change', syncSidebarToViewport)
} else {
  mobileSidebarQuery.addListener(syncSidebarToViewport)
}
const column = document.getElementById('column')
const transcript = document.getElementById('transcript')
const trajectory = document.getElementById('trajectory')
const turnRail = document.getElementById('turnRail')
const input = document.getElementById('input')
const sendBtn = document.getElementById('send')
const attachBtn = document.getElementById('attachBtn')
const imageFile = document.getElementById('imageFile')
const attachPreview = document.getElementById('attachPreview')
const composerArea = document.getElementById('composerArea')
const convTitle = document.getElementById('convTitle')
const sessionList = document.getElementById('sessionList')
const sessionSearch = document.getElementById('sessionSearch')
const modelPill = document.getElementById('modelPill')
const modelPillText = document.getElementById('modelPillText')
const popover = document.getElementById('modelPopover')
const settingsMask = document.getElementById('settingsMask')
const infoDrawer = document.getElementById('infoDrawer')
const drawerMask = document.getElementById('drawerMask')
const drawerProject = document.getElementById('drawerProject')
const assetPlatformList = document.getElementById('assetPlatformList')
const assetSummary = document.getElementById('assetSummary')
const assetList = document.getElementById('assetList')
const assetSearch = document.getElementById('assetSearch')
const assetKind = document.getElementById('assetKind')
const queryList = document.getElementById('queryList')
const infoButton = document.getElementById('infoButton')
const assetsButton = document.getElementById('assetsButton')
const projectTabs = document.getElementById('projectTabs')
const projectCsvList = document.getElementById('projectCsvList')
const collectTools = document.getElementById('collectTools')
const diskAreaList = document.getElementById('diskAreaList')
const popModelValue = document.getElementById('popModelValue')
const popEffortValue = document.getElementById('popEffortValue')
const popThinkingSwitch = document.getElementById('popThinkingSwitch')
const effortSeg = document.getElementById('effortSeg')
const untrustedSeg = document.getElementById('untrustedSeg')
const thinkingSwitch = document.getElementById('thinkingSwitch')
const themeSeg = document.getElementById('themeSeg')
const fontSeg = document.getElementById('fontSeg')
const statTurns = document.getElementById('statTurns')
const statTokens = document.getElementById('statTokens')
const statContext = document.getElementById('statContext')
const contextStat = document.getElementById('contextStat')
const contextPop = document.getElementById('contextPop')
const turnStat = document.getElementById('turnStat')
const tokenStat = document.getElementById('tokenStat')
const usagePop = document.getElementById('usagePop')
const turnPop = document.getElementById('turnPop')
const usagePopTotal = document.getElementById('usagePopTotal')
const usagePopCached = document.getElementById('usagePopCached')
const usagePopUncached = document.getElementById('usagePopUncached')
const usagePopRead = document.getElementById('usagePopRead')
const usagePopOutput = document.getElementById('usagePopOutput')
const turnPopCount = document.getElementById('turnPopCount')
const turnPopElapsed = document.getElementById('turnPopElapsed')
const turnPopTtft = document.getElementById('turnPopTtft')
const turnPopTps = document.getElementById('turnPopTps')
const ctxPercent = document.getElementById('ctxPercent')
const ctxTotal = document.getElementById('ctxTotal')
const ctxSystem = document.getElementById('ctxSystem')
const ctxTools = document.getElementById('ctxTools')
const ctxMessages = document.getElementById('ctxMessages')
const ctxBarSystem = document.getElementById('ctxBarSystem')
const ctxBarTools = document.getElementById('ctxBarTools')
const ctxBarMessages = document.getElementById('ctxBarMessages')
const menuPop = document.getElementById('menuPop')
const toastEl = document.getElementById('toast')
const renderWarnEl = document.getElementById('renderWarn')
const approvalPop = document.getElementById('approvalPop')
const approvalLabel = document.getElementById('approvalLabel')
const accessPop = document.getElementById('accessPop')
const outsideAutoState = document.getElementById('outsideAutoState')
const accessHint = document.getElementById('accessHint')
const accessLabel = document.getElementById('accessLabel')
const accessChip = document.getElementById('accessChip')
const autoHint = document.getElementById('autoHint')
const scenarioChip = document.getElementById('scenarioChip')
const scenarioLabel = document.getElementById('scenarioLabel')
const scenarioPop = document.getElementById('scenarioPop')
const workdirChip = document.getElementById('workdirChip')
const settingSessions = document.getElementById('settingSessions')
const browserStatus = document.getElementById('browserStatus')
const browserPath = document.getElementById('browserPath')
const providerList = document.getElementById('providerList')
const providerForm = document.getElementById('providerForm')
const providerListView = document.getElementById('providerListView')
const presetView = document.getElementById('presetView')
const presetBack = document.getElementById('presetBack')
const presetSearch = document.getElementById('presetSearch')
const presetCats = document.getElementById('presetCats')
const presetGrid = document.getElementById('presetGrid')
const presetCustom = document.getElementById('presetCustom')
const presetScroll = document.getElementById('presetScroll')
const presetBar = document.getElementById('presetBar')
const presetChip = document.getElementById('presetChip')
const presetChange = document.getElementById('presetChange')
const providerBehavior = document.getElementById('providerBehavior')
const pfName = document.getElementById('pfName')
const pfKind = document.getElementById('pfKind')
const pfAuth = document.getElementById('pfAuth')
const pfAuthRow = document.getElementById('pfAuthRow')
const pfBaseUrl = document.getElementById('pfBaseUrl')
const pfKey = document.getElementById('pfKey')
const pfKeyLink = document.getElementById('pfKeyLink')
const pfModels = document.getElementById('pfModels')
const pfFetchModels = document.getElementById('pfFetchModels')
const pfDelete = document.getElementById('pfDelete')
const pfCancel = document.getElementById('pfCancel')
const pfSave = document.getElementById('pfSave')
const providerFormTitle = document.getElementById('providerFormTitle')
const modelPicker = document.getElementById('modelPicker')
const modelFilter = document.getElementById('modelFilter')
const modelList = document.getElementById('modelList')
const modelClose = document.getElementById('modelClose')
const popModelList = document.getElementById('popModelList')
const limitTurnTokens = document.getElementById('limitTurnTokens')
const limitSessionTokens = document.getElementById('limitSessionTokens')
const repeatLimit = document.getElementById('repeatLimit')
const sidebarResizer = document.getElementById('sidebarResizer')
const pfPriceIn = document.getElementById('pfPriceIn')
const pfPriceOut = document.getElementById('pfPriceOut')
const pfPriceCached = document.getElementById('pfPriceCached')
const pfCurrency = document.getElementById('pfCurrency')
const pfContextWindow = document.getElementById('pfContextWindow')
const pfMaxTokens = document.getElementById('pfMaxTokens')
const pfCategory = document.getElementById('pfCategory')
const pfNotes = document.getElementById('pfNotes')
const pfWebsite = document.getElementById('pfWebsite')
const pfEndpoints = document.getElementById('pfEndpoints')
const pfCheck = document.getElementById('pfCheck')
const pfSpeedTest = document.getElementById('pfSpeedTest')
const pfSpeedResult = document.getElementById('pfSpeedResult')
const pfSpeedList = document.getElementById('pfSpeedList')
const pfIconPick = document.getElementById('pfIconPick')
const pfIconClear = document.getElementById('pfIconClear')
const pfIconColor = document.getElementById('pfIconColor')
const pfIconPreview = document.getElementById('pfIconPreview')
const pfFailover = document.getElementById('pfFailover')
const failoverSwitch = document.getElementById('failoverSwitch')
const providerSearch = document.getElementById('providerSearch')
const providerExport = document.getElementById('providerExport')
const providerImport = document.getElementById('providerImport')
const providerIoMask = document.getElementById('providerIoMask')
const providerIoTitle = document.getElementById('providerIoTitle')
const providerIoHint = document.getElementById('providerIoHint')
const providerIoText = document.getElementById('providerIoText')
const providerIoCopy = document.getElementById('providerIoCopy')
const providerIoCancel = document.getElementById('providerIoCancel')
const providerIoOk = document.getElementById('providerIoOk')
const iconMask = document.getElementById('iconMask')
const iconSearch = document.getElementById('iconSearch')
const iconGrid = document.getElementById('iconGrid')
const iconClose = document.getElementById('iconClose')

/* ---------- 本地控制面令牌（页面由服务端注入 meta） ---------- */
const API_TOKEN = document.querySelector('meta[name="spirit-api-token"]')?.content || ''
if (API_TOKEN) {
  const rawFetch = window.fetch.bind(window)
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : (input?.url || '')
    if (url.startsWith('/api/')) {
      const headers = new Headers(init.headers || {})
      headers.set('X-Spirit-Token', API_TOKEN)
      init = { ...init, headers }
    }
    return rawFetch(input, init)
  }
}

/* ---------- 状态 ---------- */
const state = {
  thinking: false,
  thinkingNow: false,
  assistantSpoken: false,
  turnHasMeta: false,
  effort: 'high',
  model: '',
  workdir: '',
  turns: 0,
  steps: 0,
  chars: 0,
  rate: 0,
  turnChars: 0,
  turnStart: 0,
  firstTokenAt: 0,
  lastTokenAt: 0,
  turnElapsed: 0,
  phase: '',
  phaseStart: 0,
  phaseElapsed: { waiting: 0, thinking: 0, writing: 0, tools: 0 },
  reasoningChars: 0,
  toolCount: 0,
  toolDone: 0,
  currentTool: '',
  lastBreakdown: '',
  ttftSum: 0,
  ttftCount: 0,
  tps: 0,
  turnHead: null,
  idleTimer: 0,
  currentSession: null,
  sessionId: 'primary',
  historyLimit: 40,
  running: false,
  stopRequested: false,
  view: 'chat',
  approval: 'ask',
  access: 'workspace',
  outsideAuto: true,
  pendingImages: [],
  untrusted: 'confirm',
  scenario: 'daily',
  scenarioLocked: false,
  scenarios: [],
  sessionDir: '',
  configPath: '',
  providerId: '',
  build: '',
  providers: [],
  providerSearch: '',
  dragId: '',
  health: {},
  balance: {},
  formIcon: '',
  formIconColor: '',
  ioMode: '',
  editingProvider: null,
  presetCategory: '全部',
  preset: null,
  providerDirty: false,
  fetchedModels: [],
  selectedModels: [],
  usage: null,
  context: null,
  limits: { turn: 0, session: 0, repeat: 3 },
  failover: false,
  scope: [],
  turnBodies: [],      // 本轮已出现的助手正文（用于把过程收进折叠块）
  turnProcess: null,   // 过程折叠块
  turnProcessCount: 0,
  turnToken: 0,        // 轮次令牌：过期定时器不能收尾新一轮
}

const EFFORTS = ['low', 'high', 'max']
const EFFORT_ALIASES = { minimal: 'low', medium: 'high', xhigh: 'high', ultra: 'max' }
const normalizeEffort = (value) => {
  const key = String(value || '').toLowerCase()
  const mapped = EFFORT_ALIASES[key] || key
  return EFFORTS.includes(mapped) ? mapped : 'high'
}

/* 桌面壳：自绘标题栏（只在 Electron 里出现）；授权范围入口在场景浮层里。
   兜底：即使 ?desktop=1 丢了（旧壳 / 缓存页），只要跑在 Electron 里就按桌面模式走，
   否则原生窗口控件会盖住页面右上角，菜单按钮既看不见也点不到。 */
const DESKTOP = new URLSearchParams(location.search).get('desktop') === '1'
  || /Electron/i.test(navigator.userAgent)
const titlebarEl = document.getElementById('titlebar')
const scopeMask = document.getElementById('scopeMask')
const scopeInput = document.getElementById('scopeInput')
const EFFORT_LABEL = { low: 'Low', high: 'High', max: 'Max' }

/* ---------- 偏好 ---------- */
const prefs = Object.assign(
  { theme: 'system', fontSize: '14' },
  JSON.parse(localStorage.getItem('spirit.prefs') || '{}'),
)

function savePrefs() {
  localStorage.setItem('spirit.prefs', JSON.stringify(prefs))
}

let systemDarkOverride = null
window.addEventListener('spirit-system-theme', (event) => {
  const value = event?.detail?.dark
  systemDarkOverride = typeof value === 'boolean' ? value : null
  if (prefs.theme === 'system') applyPrefs()
})

function systemPrefersDark() {
  if (typeof systemDarkOverride === 'boolean') return systemDarkOverride
  return matchMedia('(prefers-color-scheme: dark)').matches
}

function applyPrefs() {
  const dark = prefs.theme === 'dark'
    || (prefs.theme === 'system' && systemPrefersDark())
  document.body.dataset.theme = dark ? 'dark' : 'light'

  const size = Number(prefs.fontSize) || 14
  const root = document.documentElement.style
  root.setProperty('--spirit-content-font-size', `${size}px`)
  root.setProperty('--spirit-content-font-delta', `${size - 14}px`)
  root.setProperty('--spirit-content-font-size-secondary', `${Math.max(11, size - 1)}px`)
  root.setProperty('--spirit-content-font-delta-secondary', `${size - 15}px`)

  markSegmented(themeSeg, prefs.theme)
  markSegmented(fontSeg, prefs.fontSize)
}

matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  if (prefs.theme === 'system') applyPrefs()
})
// 从别的窗口切回来时再对一次系统主题（Electron 偶尔漏掉 media change）
window.addEventListener('focus', () => {
  if (prefs.theme === 'system') applyPrefs()
})
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && prefs.theme === 'system') applyPrefs()
})

/* ---------- 小工具 ---------- */
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ))
}

marked.use({
  gfm: true,
  breaks: true,
  renderer: {
    html(token) {
      const raw = typeof token === 'string' ? token : (token?.text ?? token?.raw ?? '')
      return escapeHtml(raw)
    },
  },
})

const renderMarkdown = (text) => {
  // 流式渲染的“增量”统计：测试用来确认长回复没有整段反复解析
  const stats = window.__spiritMarkdownStats
  if (stats) {
    stats.calls += 1
    stats.chars += text.length
  }
  return marked.parse(text)
}

/**
 * 找最后一个「稳定块边界」：空行之前的内容不会再变，可以只渲染一次。
 * 围栏代码块里的空行不算边界，避免把代码块拆成两半。
 */
function markdownStableLength(text) {
  let fence = ''
  let offset = 0
  let boundary = 0
  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    const match = trimmed.match(/^(`{3,}|~{3,})/)
    if (fence) {
      if (match && match[1][0] === fence[0] && match[1].length >= fence.length) fence = ''
    } else if (match) {
      fence = match[1]
    } else if (!trimmed && offset > 0) {
      boundary = offset + line.length + 1
    }
    offset += line.length + 1
  }
  return boundary
}

/** 流式增量：稳定前缀只渲染一次，只有最后一段（还在长的）每次重解析。 */
function patchAssistantMarkdown(a) {
  const text = a.text
  if (!a.stableEl) {
    a.md.innerHTML = ''
    a.stableEl = document.createElement('div')
    a.stableEl.className = 'mdStable'
    a.tailEl = document.createElement('div')
    a.tailEl.className = 'mdTail'
    a.md.appendChild(a.stableEl)
    a.md.appendChild(a.tailEl)
    a.stableLen = 0
  }
  let boundary = markdownStableLength(text)
  if (boundary < a.stableLen) {          // 文本被替换 / 回退：从头重来
    a.stableEl.innerHTML = ''
    a.stableLen = 0
  }
  if (boundary > a.stableLen) {
    const holder = document.createElement('div')
    holder.innerHTML = renderMarkdown(text.slice(a.stableLen, boundary))
    while (holder.firstChild) a.stableEl.appendChild(holder.firstChild)
    a.stableLen = boundary
  }
  a.tailEl.innerHTML = renderMarkdown(text.slice(a.stableLen))
}

function toast(message) {
  toastEl.textContent = message
  toastEl.hidden = false
  clearTimeout(toast._timer)
  toast._timer = setTimeout(() => { toastEl.hidden = true }, 2200)
}

function addFlow(el) {
  const wrap = document.createElement('div')
  wrap.className = 'flow-item'
  wrap.appendChild(el)
  column.appendChild(wrap)
  return wrap
}

function nearBottom() {
  return transcript.scrollHeight - transcript.scrollTop - transcript.clientHeight < 120
}

function scrollToBottom(force = false) {
  if (force || nearBottom()) transcript.scrollTop = transcript.scrollHeight
}

function nowTime() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const WINDOW_TITLE = 'Spirit'

function setTitle(title) {
  convTitle.textContent = title || '新会话'
  // 窗口标题固定，不跟当前会话名 / 路径跑
  document.title = WINDOW_TITLE
}

/* ---------- 统计 ---------- */
function formatTokens(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}K` : String(n)
}

function updateStats() {
  const rate = state.rate > 0 ? ` · ${state.rate} tok/s` : ''
  statTurns.textContent = `${state.turns} 轮 ${state.steps} 步${rate}`

  const session = state.usage?.session || {}
  const turn = state.usage?.turn || {}
  const tokens = Number(session.total || 0)
  const symbol = session.currency === 'USD' ? '$' : '¥'
  const mixed = session.mixed ? '*' : ''
  const cost = session.priced ? ` · ${symbol}${Number(session.cost || 0).toFixed(4)}${mixed}` : ''
  statTokens.textContent = `${formatTokens(tokens)} tok${cost}`
  statTokens.title = session.requests
    ? `请求 ${session.requests} · 输入 ${session.input} · 输出 ${session.output} · 缓存 ${session.cached}`
      + (state.limits.turn ? ` · 本轮 ${turn.total}/${state.limits.turn}` : '')
      + (state.limits.session ? ` · 会话 ${session.total}/${state.limits.session}` : '')
    : '还没有请求'

  const last = state.usage?.last
  const windowSize = Number(state.usage?.window || 128000)
  const percent = last && windowSize
    ? Math.min(100, (Number(last.input || 0) / windowSize) * 100)
    : 0
  statContext.textContent = `${percent.toFixed(1)}%`
  statContext.title = last
    ? `上次请求输入 ${last.input} tok / 窗口 ${windowSize}`
    : '还没有请求'
  renderStatsPops()
}

function formatExact(n) {
  return Math.round(Number(n || 0)).toLocaleString('en-US')
}

function renderUsagePop() {
  const session = state.usage?.session || {}
  const input = Number(session.input || 0)
  const output = Number(session.output || 0)
  const cached = Number(session.cached || 0)
  const total = Number(session.total || 0) || input + output
  const hit = input > 0 ? (cached / input) * 100 : 0
  usagePopTotal.textContent = `${formatExact(total)} tok`
  usagePopCached.textContent = `${hit.toFixed(0)}%`
  usagePopUncached.textContent = `${formatExact(Math.max(0, input - cached))} tok`
  usagePopRead.textContent = `${formatExact(cached)} tok`
  usagePopOutput.textContent = `${formatExact(output)} tok`
}

function renderTurnPop() {
  turnPopCount.textContent = `${state.turns} 轮 ${state.steps} 步`
  const modelEnd = state.lastTokenAt || (state.turnStart ? performance.now() : 0)
  const elapsed = state.turnElapsed > 0
    ? state.turnElapsed
    : (state.turnStart && modelEnd ? (modelEnd - state.turnStart) / 1000 : 0)
  turnPopElapsed.textContent = elapsed > 0 ? `${elapsed.toFixed(1)} 秒` : '—'

  const currentTtft = state.firstTokenAt && state.turnStart
    ? Math.max(0, (state.firstTokenAt - state.turnStart) / 1000)
    : 0
  const count = state.ttftCount + (currentTtft > 0 && state.running ? 1 : 0)
  const ttft = count > 0
    ? (state.ttftSum + (currentTtft > 0 && state.running ? currentTtft : 0)) / count
    : 0
  turnPopTtft.textContent = ttft > 0 ? `${ttft.toFixed(1)} 秒` : '—'

  let tps = state.tps
  if (!tps && state.firstTokenAt && state.lastTokenAt > state.firstTokenAt) {
    const tokens = Number(state.usage?.turn?.output || 0)
      || Math.round(state.turnChars / 4)
    const decode = (state.lastTokenAt - state.firstTokenAt) / 1000
    tps = tokens > 0 && decode > 0.05 ? Math.round(tokens / decode) : 0
  }
  turnPopTps.textContent = tps > 0 ? `${tps} tok/s` : '—'
}

function renderStatsPops() {
  renderUsagePop()
  renderTurnPop()
}

function sessionUrl(url) {
  if (!state.sessionId || state.sessionId === 'primary') return url
  return url + (url.includes('?') ? '&' : '?')
    + `session=${encodeURIComponent(state.sessionId)}`
}

async function loadUsage() {
  try {
    state.usage = await fetch(sessionUrl('/api/usage')).then((res) => res.json())
    updateStats()
  } catch { /* 引擎未起 */ }
}

function formatCount(n) {
  const value = Number(n || 0)
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value % 1_000_000 ? 1 : 0)}M`
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}K`
  }
  return String(Math.round(value))
}

async function loadContext() {
  try {
    state.context = await fetch(sessionUrl('/api/context')).then((res) => res.json())
    renderContext()
  } catch { /* 引擎未起 */ }
}

function renderContext() {
  const data = state.context || {}
  const total = Number(data.total || 0)
  const windowSize = Number(data.window || 0)
  const percent = windowSize ? (total / windowSize) * 100 : 0
  ctxPercent.textContent = percent > 0 ? `${percent.toFixed(1)}%` : '0%'
  ctxTotal.textContent = `~${formatCount(total)} / ${formatCount(windowSize)}`
  ctxSystem.textContent = `~${formatCount(data.system || 0)}`
  ctxTools.textContent = `~${formatCount(data.tools || 0)}`
  ctxMessages.textContent = `~${formatCount(data.messages || 0)}`
  for (const [element, value] of [
    [ctxBarSystem, data.system],
    [ctxBarTools, data.tools],
    [ctxBarMessages, data.messages],
  ]) {
    element.style.width = total > 0 ? `${Math.min(100, (Number(value || 0) / total) * 100)}%` : '0%'
  }
}

function positionStatsPop(pop, anchor) {
  const rect = anchor.getBoundingClientRect()
  const width = pop.offsetWidth
  const height = pop.offsetHeight
  pop.style.left = `${Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12))}px`
  pop.style.top = `${Math.max(12, rect.top - height - 10)}px`
}

function positionContextPop() {
  positionStatsPop(contextPop, contextStat)
}

function closeStatPops(except = null) {
  for (const pop of [contextPop, usagePop, turnPop]) {
    if (pop !== except) pop.hidden = true
  }
}

/* ---------- 轮次 ---------- */
function markRail() {
  const mark = document.createElement('span')
  mark.className = 'rail-mark'
  mark.title = `第 ${state.turns} 轮`
  mark.addEventListener('click', () => {
    const heads = column.querySelectorAll('.turnHead')
    const head = heads[state.turns - 1]
    if (head) head.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
  turnRail.appendChild(mark)
  for (const m of turnRail.querySelectorAll('.rail-mark')) m.classList.remove('active')
  mark.classList.add('active')
}

let runningPoll = 0

function startRunningPoll() {
  stopRunningPoll()
  runningPoll = setInterval(async () => {
    const head = state.turnHead
    const token = state.turnToken
    if (!head || head.dataset.done === '1') return
    try {
      const [data, kernel] = await Promise.all([
        fetch(sessionUrl('/api/running')).then((res) => res.json()),
        fetch(sessionUrl('/api/kernel')).then((res) => res.json()).catch(() => null),
      ])
      if (token !== state.turnToken || state.turnHead !== head) return
      const calls = data.calls || []
      if (head.dataset.done === '1') return
      // 窗口被遮住时浏览器会节流定时器，assistant_end 的 3 秒兜底可能迟到：
      // 以内核状态为准；必须同时没有在跑的工具，才收尾。
      if (kernel?.cpu && kernel.cpu.turn_active === false
          && Number(kernel.running || 0) === 0
          && performance.now() - (state.turnStart || 0) > 3000) {
        finishTurn(false, token)
        return
      }
      const phaseSeconds = Math.max(
        0,
        Math.round((performance.now() - (state.phaseStart || performance.now())) / 1000),
      )
      let text
      if (kernel?.retry?.active && state.phase !== 'tools' && !calls.length) {
        const reason = String(kernel.retry.error || '').split(' · ')[0].slice(0, 40)
        text = `模型服务异常，正在重试 ${kernel.retry.attempt}/${kernel.retry.limit}…`
          + (reason ? `（${reason}）` : '')
      } else if (state.phase === 'tools' || calls.length) {
        const call = calls[0]
        const more = calls.length > 1 ? ` +${calls.length - 1}` : ''
        const name = call?.name || state.currentTool || '工具'
        const elapsed = call?.elapsed ?? phaseSeconds
        const done = state.toolDone
        const total = Math.max(state.toolCount, done)
        text = `执行工具 ${name}${more}… ${elapsed}s（${done}/${total}）`
      } else if (state.phase === 'thinking') {
        text = `思考中… ${phaseSeconds}s · ${formatCount(state.reasoningChars)} 字`
      } else if (state.phase === 'writing') {
        text = `正在写回复… ${phaseSeconds}s · ${formatCount(state.turnChars)} 字`
      } else {
        text = phaseSeconds >= 2
          ? `等待模型响应… ${phaseSeconds}s`
          : '等待模型响应…'
      }
      if (state.phase !== 'tools' && !calls.length && phaseSeconds >= 30) {
        text += '（上游仍在生成，可停止）'
      }
      state.turnHead.textContent = text
    } catch { /* 引擎未起 */ }
  }, 700)
}

function stopRunningPoll() {
  clearInterval(runningPoll)
  runningPoll = 0
}

/** 切会话 / 新建会话：作废上一轮的定时器与收尾回调。 */
function leaveTurn() {
  clearTimeout(state.idleTimer)
  state.idleTimer = 0
  state.turnToken += 1
  stopRunningPoll()
  state.turnHead = null
}

/** 记录“当前阶段”耗时：等待模型 / 思考 / 写正文 / 执行工具。 */
function markPhase(next) {
  if (!state.turnHead || state.phase === next) return
  const now = performance.now()
  if (state.phase && state.phaseStart) {
    state.phaseElapsed[state.phase] += now - state.phaseStart
  }
  state.phase = next
  state.phaseStart = now
}

function flushPhase() {
  if (!state.turnHead) return
  if (state.phase && state.phaseStart) {
    state.phaseElapsed[state.phase] += performance.now() - state.phaseStart
  }
  state.phase = ''
  state.phaseStart = 0
}

function startTurn() {
  clearTimeout(state.idleTimer)
  state.idleTimer = 0
  state.turnToken += 1
  state.turns += 1
  state.turnStart = performance.now()
  state.thinkingNow = false
  state.turnChars = 0
  state.firstTokenAt = 0
  state.lastTokenAt = 0
  state.turnElapsed = 0
  state.phase = 'waiting'
  state.phaseStart = state.turnStart
  state.phaseElapsed = { waiting: 0, thinking: 0, writing: 0, tools: 0 }
  state.reasoningChars = 0
  state.toolCount = 0
  state.toolDone = 0
  state.currentTool = ''
  state.lastBreakdown = ''
  state.tps = 0
  state.rate = 0
  state.turnBodies = []
  state.turnProcess = null
  state.turnProcessCount = 0

  const head = document.createElement('div')
  head.className = 'turnHead'
  head.textContent = '等待模型响应…'
  addFlow(head)
  state.turnHead = head
  markRail()
  updateStats()
  startRunningPoll()
}

// 测试钩子：模拟“新一轮开始”，用来验证旧轮的 idle 定时器不会误收尾
window.__spiritStartTurn = startTurn

function activity() {
  if (!state.turnHead) return
  clearTimeout(state.idleTimer)
  state.idleTimer = 0
  if (state.turnHead.dataset.done === '1') {
    state.turnHead.dataset.done = '0'
    state.turnHead.classList.remove('failed')
    state.turnHead.textContent = '等待模型响应…'
  }
}

function scheduleIdle() {
  clearTimeout(state.idleTimer)
  // 一段模型输出说完 ≠ 本轮结束：CPU 可能还在跑工具或继续问模型。
  // 令牌 + turn_active + 本会话正在执行的工具，三者都满足才收尾。
  const token = state.turnToken
  const head = state.turnHead
  state.idleTimer = setTimeout(async () => {
    if (token !== state.turnToken || state.turnHead !== head) return
    try {
      const kernel = await fetch(sessionUrl('/api/kernel')).then((res) => res.json())
      if (token !== state.turnToken || state.turnHead !== head) return
      if (kernel?.cpu?.turn_active === true) return
      if (Number(kernel?.running || 0) > 0) return
    } catch {
      return   // 取不到状态就不收尾，交给运行轮询继续判断
    }
    finishTurn(false, token)
  }, 800)
}

function finishTurn(failed, token) {
  if (token !== undefined && token !== state.turnToken) return
  clearTimeout(state.idleTimer)
  state.idleTimer = 0
  stopRunningPoll()
  const userStopped = !!state.stopRequested
  const stopped = !!failed || userStopped
  state.stopRequested = false
  const head = state.turnHead
  const beforeFlush = performance.now()
  flushPhase()
  state.turnHead = null
  state.thinkingNow = false
  if (head) {
    const now = beforeFlush
    const seconds = Math.max(1, Math.round((now - state.turnStart) / 1000))
    const modelEnd = state.lastTokenAt || now
    const elapsed = Math.max(0, (modelEnd - state.turnStart) / 1000)
    state.turnElapsed = elapsed
    const ttft = state.firstTokenAt
      ? Math.max(0, (state.firstTokenAt - state.turnStart) / 1000)
      : 0
    if (ttft > 0) {
      state.ttftSum += ttft
      state.ttftCount += 1
    }
    const outputTokens = Number(state.usage?.turn?.output || 0)
      || Math.round(state.turnChars / 4)
    const decode = state.firstTokenAt && state.lastTokenAt > state.firstTokenAt
      ? (state.lastTokenAt - state.firstTokenAt) / 1000
      : Math.max(0, elapsed - ttft)
    state.tps = outputTokens > 0 && decode > 0.05
      ? Math.round(outputTokens / decode)
      : 0
    state.rate = state.tps
    head.dataset.done = '1'
    head.classList.toggle('failed', stopped)
    const label = userStopped ? '已停止' : (failed ? '处理失败' : '已完成')
    head.innerHTML = `<span class="caret"></span><span>${label}，用时 ${seconds} 秒</span>`
    processSummary()
    const phase = state.phaseElapsed
    const round = (ms) => Math.max(0, Math.round(ms / 1000))
    state.lastBreakdown = [
      `总 ${seconds}s`,
      `等待模型 ${round(phase.waiting)}s`,
      `思考 ${round(phase.thinking)}s`,
      `正文输出 ${round(phase.writing)}s`,
      `工具 ${round(phase.tools)}s`,
    ].join(' · ')
    head.title = state.lastBreakdown
  }

  for (const entry of toolRows) {
    if (entry.status) {
      entry.status.textContent = userStopped ? '已中断' : '未返回'
      entry.status.classList.add('done')
    }
  }
  settleToolGroup(userStopped ? '已中断' : '未返回')
  toolRows.length = 0
  toolRowsById.clear()

  state.running = false
  updateSendButton()
  updateStats()
  refreshSessions()
  refreshStatus()
}

/* ---------- 输入按钮 ---------- */
function updateSendButton() {
  if (state.running) {
    sendBtn.classList.add('stopping')
    sendBtn.disabled = false
    sendBtn.title = '停止'
    sendBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="2" width="8" height="8" rx="1.6" fill="currentColor"/></svg>'
    return
  }
  sendBtn.classList.remove('stopping')
  sendBtn.disabled = !input.value.trim() && !state.pendingImages.length
  sendBtn.title = '发送'
  sendBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 13V3M8 3L3.5 7.5M8 3l4.5 4.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
}

/* ---------- 用户 ---------- */
function addUser(text, images = []) {
  shell.classList.remove('hero')

  const row = document.createElement('div')
  row.className = 'userRow'

  const stack = document.createElement('div')
  stack.className = 'userStack'

  const bubble = document.createElement('div')
  bubble.className = 'userBubble'
  if (text) bubble.textContent = text
  if (images.length) {
    const gallery = document.createElement('div')
    gallery.className = 'userImages'
    for (const src of images) {
      const img = document.createElement('img')
      img.src = src
      img.alt = '图片'
      gallery.appendChild(img)
    }
    bubble.appendChild(gallery)
  }

  const meta = document.createElement('div')
  meta.className = 'msg-meta'
  const time = document.createElement('span')
  time.textContent = nowTime()
  const copy = document.createElement('button')
  copy.className = 'copy-btn'
  copy.title = '复制'
  copy.innerHTML = '<svg width="13" height="13" viewBox="0 0 16 16" fill="none"><rect x="5.2" y="5.2" width="8" height="8" rx="1.6" stroke="currentColor" stroke-width="1.2"/><path d="M10.8 5.2V4c0-.9-.7-1.6-1.6-1.6H4c-.9 0-1.6.7-1.6 1.6v5.2c0 .9.7 1.6 1.6 1.6h1.2" stroke="currentColor" stroke-width="1.2"/></svg>'
  copy.addEventListener('click', () => navigator.clipboard?.writeText(text))
  meta.appendChild(time)
  meta.appendChild(copy)

  stack.appendChild(bubble)
  row.appendChild(stack)
  row.appendChild(meta)
  const wrap = addFlow(row)
  state.turnTop = wrap   // 本轮工具面板插在它后面（最上面）
  state.assistantSpoken = false
  state.turnHasMeta = false
  turnMeta = null
  turnDivider = null
  toolGroup = null
  reasoning = null
  reasoningBlock = null
  scrollToBottom(true)

  state.chars += text.length
  updateStats()
}

/* ---------- 思考 ---------- */
let reasoning = null        // 当前正在流的一段
let reasoningBlock = null   // 本轮共用一个折叠块：所有思考段都收进它

function ensureReasoningBlock() {
  if (reasoningBlock && reasoningBlock.details.isConnected) return reasoningBlock
  const details = document.createElement('details')
  details.className = 'reasoningBlock'
  details.open = false         // 默认折叠；标题里显示“生成中 / N 字”，要看细节再点开
  const summary = document.createElement('summary')
  summary.textContent = '深度思考'
  const body = document.createElement('div')
  body.className = 'r-body'
  details.appendChild(summary)
  details.appendChild(body)
  summary.addEventListener('click', () => {
    if (reasoningBlock) reasoningBlock.manual = true
  })
  ensureTurnMeta().body.appendChild(details)
  reasoningBlock = {
    details, body, summary,
    text: '', segments: 0, manual: false,
  }
  return reasoningBlock
}

function appendReasoningSegment(block, text) {
  const piece = String(text || '').trim()
  if (!piece) return
  block.text = block.text ? `${block.text}\n\n${piece}` : piece
  block.segments += 1
  block.summary.textContent = block.segments > 1
    ? `深度思考 · ${block.segments} 段`
    : '深度思考'
  block.body.textContent = block.text
}

function ensureReasoning() {
  if (reasoning) return reasoning
  const block = ensureReasoningBlock()
  reasoning = { block, text: '', raf: 0 }
  return reasoning
}

function pushReasoningDelta(delta) {
  activity()
  state.thinkingNow = true
  markPhase('thinking')
  state.reasoningChars += String(delta || '').length
  const now = performance.now()
  const r = ensureReasoning()
  r.text += delta
  if (!r.raf && now - (r.lastRender || 0) >= 80) {
    r.raf = requestAnimationFrame(() => {
      r.raf = 0
      r.lastRender = performance.now()
      r.block.body.textContent = r.block.text
        ? `${r.block.text}\n\n${r.text}`
        : r.text
      r.block.summary.textContent = `深度思考 · 生成中 · ${formatCount(
        r.block.text.length + r.text.length,
      )} 字`
      scrollToBottom()
    })
  }
  scrollToBottom()
}

function endReasoning() {
  if (!reasoning) return
  const r = reasoning
  reasoning = null
  if (r.raf) cancelAnimationFrame(r.raf)
  appendReasoningSegment(r.block, r.text)
  if (!r.block.manual) r.block.details.open = false   // 想完了收起来
}

function addReasoning(text) {
  if (reasoning) {
    // 边流边来的整段记录：以整段为准，收尾同一个块，不另起一块
    reasoning.text = text
    endReasoning()
    return
  }
  const block = ensureReasoningBlock()
  appendReasoningSegment(block, text)
  if (!block.manual) block.details.open = false
  scrollToBottom()
}

/* ---------- 助手 ---------- */
let assistant = null
let lastAssistant = null   // 最近一个助手块（用于整段校正）

function resetTurnBodies() {
  state.turnBodies = []
  state.turnProcess = null
  state.turnProcessCount = 0
}

function processSummary() {
  if (!state.turnProcess) return
  const seconds = state.turnStart
    ? Math.max(1, Math.round((performance.now() - state.turnStart) / 1000))
    : 0
  const time = seconds ? ` · ${seconds}s` : ''
  state.turnProcess.summary.textContent =
    `过程 · ${state.turnProcessCount} 段${time}`
}

/** 把本轮此前的助手正文收进一个“过程”折叠块；最后一段留作结论。 */
function foldAssistantBodies() {
  if (!state.turnBodies.length) return
  const first = state.turnBodies[0].flow
  if (!first || !first.isConnected) {
    state.turnBodies = []
    return
  }
  if (!state.turnProcess) {
    const details = document.createElement('details')
    details.className = 'processBlock'
    details.open = false
    const summary = document.createElement('summary')
    summary.textContent = '过程'
    const body = document.createElement('div')
    body.className = 'processBlockBody'
    details.append(summary, body)
    const wrap = document.createElement('div')
    wrap.className = 'flow-item'
    wrap.appendChild(details)
    column.insertBefore(wrap, first)
    state.turnProcess = { details, summary, body, wrap }
  }
  for (const item of state.turnBodies) {
    if (!item.flow.isConnected) continue
    item.flow.classList.add('processItem')
    state.turnProcess.body.appendChild(item.flow)
    state.turnProcessCount += 1
  }
  state.turnBodies = []
  processSummary()
}

function registerAssistantBody(body) {
  foldAssistantBodies()
  const flow = addFlow(body)
  state.turnBodies.push({ body, flow })
  return flow
}

function ensureAssistant() {
  if (assistant) return assistant
  const body = document.createElement('div')
  body.className = 'assistantBody'
  const firstBody = !state.assistantSpoken
  if (firstBody) {
    state.assistantSpoken = true
    if (state.turnHasMeta) {
      ensureTurnDivider()
      body.classList.add('afterMeta')
    }
  } else {
    body.classList.add('continued')
  }
  const md = document.createElement('div')
  md.className = 'markdownBody'
  body.appendChild(md)
  registerAssistantBody(body)
  assistant = { body, md, text: '', raf: 0 }
  lastAssistant = { body, md }
  return assistant
}

function applyAssistantFinal(text) {
  activity()
  // 后端在流结束后给整段原文：拿它校正页面（SSE 丢片段也能补回来）
  if (assistant) {
    const a = assistant
    const extra = text.length - a.text.length
    if (extra > 0) {
      state.chars += extra
      state.turnChars += extra
    }
    a.text = text
    endAssistant()
    return
  }
  if (lastAssistant) {
    const md = lastAssistant.md
    const before = md.textContent.length
    md.dataset.fullText = text
    md.innerHTML = renderMarkdown(text)
    const extra = text.length - before
    if (extra > 0) {
      state.chars += extra
      state.turnChars += extra
    }
    updateStats()
    return
  }
  addAssistantMessage(text)
}

function pushDelta(delta) {
  activity()
  state.thinkingNow = false
  markPhase('writing')
  const now = performance.now()
  if (!state.firstTokenAt) state.firstTokenAt = now
  state.lastTokenAt = now
  const a = ensureAssistant()
  a.text += delta
  state.chars += delta.length
  state.turnChars += delta.length
  // 限频 ~80ms；稳定段落只渲染一次，只有末尾还在长的段落每帧重解析
  if (!a.raf && now - (a.lastRender || 0) >= 80) {
    a.raf = requestAnimationFrame(() => {
      a.raf = 0
      a.lastRender = performance.now()
      patchAssistantMarkdown(a)
      scrollToBottom()
    })
  }
}

function endAssistant() {
  endReasoning()
  if (!assistant) return
  const a = assistant
  assistant = null
  if (a.raf) cancelAnimationFrame(a.raf)
  a.md.dataset.fullText = a.text
  // 流式阶段已经把稳定段 + 尾段渲染出来了；结束时再整段 innerHTML 重写
  // 会造成一次明显的闪动/行高跳动，这里只补最后一段。
  if (a.stableEl && a.tailEl) {
    a.tailEl.innerHTML = renderMarkdown(a.text.slice(a.stableLen || 0))
  } else {
    a.md.innerHTML = renderMarkdown(a.text)
  }
  scrollToBottom()
}

function addAssistantMessage(text) {
  const clean = String(text || '').trim()
  // 页面中途加载历史 + 实时 SSE 可能把同一段正文送两遍；连续的相同正文只留一份
  if (clean && lastAssistant?.md?.dataset.fullText?.trim() === clean) return
  activity()
  endAssistant()
  const body = document.createElement('div')
  body.className = 'assistantBody'
  const firstBody = !state.assistantSpoken
  if (firstBody) {
    state.assistantSpoken = true
    if (state.turnHasMeta) {
      ensureTurnDivider()
      body.classList.add('afterMeta')
    }
  } else {
    body.classList.add('continued')
  }
  const md = document.createElement('div')
  md.className = 'markdownBody'
  md.dataset.fullText = text
  md.innerHTML = renderMarkdown(text)
  body.appendChild(md)
  registerAssistantBody(body)
  lastAssistant = { body, md }
  scrollToBottom(true)
}

/* ---------- 工具 ---------- */
const toolRows = []
const toolRowsById = new Map()

function formatArgs(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return String(raw ?? '')
  }
}

const SUMMARY_KEYS = [
  'url', 'host', 'domain', 'target', 'path', 'file', 'query',
  'bashinput', 'command', 'name', 'text',
]

function summarizeArgs(raw) {
  let text = String(raw ?? '')
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      const hit = SUMMARY_KEYS.find((key) => {
        const value = parsed[key]
        return typeof value === 'string' && value.trim()
      })
      if (hit) text = parsed[hit]
      else if (Array.isArray(parsed.records)) text = `${parsed.records.length} 行`
      else if (Array.isArray(parsed.items)) text = `${parsed.items.length} 项`
    }
  } catch { /* 原样 */ }
  text = String(text).replace(/\s+/g, ' ').trim()
  return text.length > 100 ? text.slice(0, 100) + '…' : text
}

/* 本轮「执行过程」层：工具 + 思考放同一个分层容器里，正文在分隔条下方 */
let turnMeta = null
let turnDivider = null

function insertAtTurnTop(element) {
  if (state.turnTop && state.turnTop.parentNode === column) {
    let anchor = state.turnTop
    let next = anchor.nextElementSibling
    while (next) {
      const first = next.firstElementChild
      if (!first || !first.classList.contains('turnHead')) break
      anchor = next
      next = anchor.nextElementSibling
    }
    column.insertBefore(element, anchor.nextSibling)
  } else {
    column.appendChild(element)
  }
}

function ensureTurnMeta() {
  if (turnMeta && turnMeta.wrap.isConnected) return turnMeta
  const wrap = document.createElement('div')
  wrap.className = 'flow-item turnMeta'
  const body = document.createElement('div')
  body.className = 'turnMetaBody'
  wrap.appendChild(body)
  insertAtTurnTop(wrap)
  turnMeta = { wrap, body }
  state.turnHasMeta = true
  return turnMeta
}

function ensureTurnDivider() {
  if (!state.turnHasMeta) return
  if (turnDivider && turnDivider.isConnected) return
  const wrap = document.createElement('div')
  wrap.className = 'flow-item turnDivider'
  const pill = document.createElement('span')
  pill.className = 'turnDividerPill'
  pill.textContent = 'Spirit'
  wrap.appendChild(pill)
  column.appendChild(wrap)
  turnDivider = wrap
}

/* 一轮里所有工具调用收进顶部一个可折叠面板：外层「工具调用」，内层每条命令仍可单独展开。 */
let toolGroup = null

function ensureToolGroup() {
  if (toolGroup && toolGroup.row.isConnected) return toolGroup
  const details = document.createElement('details')
  details.className = 'toolGroup'
  details.open = false  // 默认折叠：标题栏显示数量 / 运行中 / 失败，细节点开看

  const head = document.createElement('summary')
  head.className = 'toolGroupHead'
  head.innerHTML =
    '<span class="toolLeading"><span class="toolCaret"></span></span>' +
    '<span class="toolGroupTitle">工具调用</span>' +
    '<span class="toolGroupMeta"></span>' +
    '<span class="toolGroupState">运行中…</span>'
  const body = document.createElement('div')
  body.className = 'toolGroupBody'
  details.appendChild(head)
  details.appendChild(body)

  head.addEventListener('click', () => {
    // 用户自己点过就不在轮末强行收起
    if (toolGroup) toolGroup.manual = true
  })

  ensureTurnMeta().body.appendChild(details)

  toolGroup = {
    row: details,
    body,
    meta: head.querySelector('.toolGroupMeta'),
    state: head.querySelector('.toolGroupState'),
    count: 0,
    returned: 0,
    failed: 0,
    manual: false,
  }
  return toolGroup
}

function updateToolGroup() {
  if (!toolGroup) return
  const group = toolGroup
  group.meta.textContent = `${group.count} 个`
  if (group.returned < group.count) {
    group.state.textContent = `运行中… ${group.returned}/${group.count}`
    group.state.classList.remove('done')
  } else {
    group.state.textContent = group.failed ? `完成 · ${group.failed} 个失败` : '已返回'
    group.state.classList.add('done')
  }
}

function settleToolGroup(label) {
  if (!toolGroup) return
  if (toolGroup.returned < toolGroup.count) {
    toolGroup.state.textContent = label || '未返回'
    toolGroup.state.classList.add('done')
  }
  // 轮末收成顶部一条；用户手动展开过、或有失败时保持展开
  if (!toolGroup.manual && !toolGroup.failed) toolGroup.row.open = false
}

function addToolCall(name, args, callId) {
  activity()
  endAssistant()
  foldAssistantBodies()   // 开始下一次工具调用：上一段正文立即收进“过程”
  markPhase('tools')
  state.toolCount += 1
  state.currentTool = name
  const group = ensureToolGroup()

  const row = document.createElement('details')
  row.className = 'toolRow'

  const head = document.createElement('summary')
  head.className = 'toolHead'
  const line = document.createElement('div')
  line.className = 'toolLine'
  line.innerHTML =
    '<span class="toolLeading"><span class="toolCaret"></span></span>' +
    '<span class="toolTitle"></span><span class="toolSep"></span><span class="toolSummary"></span>' +
    '<span class="toolLive" hidden></span><span class="toolState">进行中</span>'
  line.querySelector('.toolTitle').textContent = name
  line.querySelector('.toolSummary').textContent = summarizeArgs(args)

  const preview = document.createElement('div')
  preview.className = 'toolPreview'
  preview.hidden = true
  head.appendChild(line)

  const body = document.createElement('div')
  body.className = 'toolBody'
  // 预览放进展开体里：收起时只剩一行“工具 + 参数摘要 + 状态”
  body.appendChild(preview)

  const argsLabel = document.createElement('div')
  argsLabel.className = 'toolLabel'
  argsLabel.textContent = '参数'
  const argsPre = document.createElement('pre')
  argsPre.className = 'toolPre'
  argsPre.textContent = formatArgs(args)

  const output = document.createElement('div')
  const outLabel = document.createElement('div')
  outLabel.className = 'toolLabel'
  outLabel.textContent = '结果'
  const outPre = document.createElement('pre')
  outPre.className = 'toolPre'
  output.hidden = true
  output.appendChild(outLabel)
  output.appendChild(outPre)

  body.appendChild(argsLabel)
  body.appendChild(argsPre)
  body.appendChild(output)

  row.appendChild(head)
  row.appendChild(body)
  group.body.appendChild(row)

  const entry = {
    row,
    id: String(callId || ''),
    preview,
    output,
    outPre,
    status: line.querySelector('.toolState'),
    live: line.querySelector('.toolLive'),
    liveText: '',
    raf: 0,
  }
  toolRows.push(entry)
  if (entry.id) toolRowsById.set(entry.id, entry)
  group.count += 1
  updateToolGroup()
  state.steps += 1
  state.chars += String(args || '').length
  updateStats()
  scrollToBottom()
}

function appendToolDelta(callId, text) {
  const key = String(callId || '')
  const entry = key ? toolRowsById.get(key) : null
  if (!entry || !text) return
  entry.liveText += text
  if (entry.liveText.length > 4000) entry.liveText = entry.liveText.slice(-4000)
  // 大输出时 delta 很密：一帧只重设一次文本节点，别每个片段都重建 DOM
  if (entry.raf) return
  entry.raf = requestAnimationFrame(() => {
    entry.raf = 0
    const lastLine = entry.liveText.split(/\r?\n/).filter((line) => line.trim()).pop() || ''
    if (entry.live) {
      entry.live.textContent = lastLine.trim().slice(0, 120)
      entry.live.hidden = !lastLine.trim()
    }
    entry.outPre.textContent = entry.liveText
    entry.output.hidden = false
    scrollToBottom()
  })
}

function addToolResult(name, content, callId) {
  activity()
  const key = String(callId || '')
  let entry = key ? toolRowsById.get(key) : null
  if (entry) {
    const index = toolRows.indexOf(entry)
    if (index >= 0) toolRows.splice(index, 1)
    toolRowsById.delete(key)
  } else {
    entry = toolRows.shift() || null
  }
  if (entry) {
    if (entry.raf) {
      cancelAnimationFrame(entry.raf)   // 别再让延迟帧用 liveText 覆盖最终结果
      entry.raf = 0
    }
    entry.output.hidden = false
    entry.outPre.textContent = content
    const text = String(content || '')
    const firstLine = text.split(/\r?\n/).find((line) => line.trim()) || ''
    const lines = text.split(/\r?\n/).length
    entry.preview.hidden = !firstLine
    entry.preview.textContent = firstLine.trim().slice(0, 140)
      + (lines > 1 ? ` · ${lines} 行` : '')
    entry.preview.title = firstLine.trim()
    if (entry.live) entry.live.hidden = true
    entry.liveText = ''
    const failed = /^(沙箱拒绝|错误|失败|命令.*失败|异常)|Traceback|Error:/.test(text.trim())
    if (failed) {
      entry.row.classList.add('failed')   // 失败只改状态；默认保持折叠
    }
    if (entry.status) {
      entry.status.textContent = failed ? '失败' : '已返回'
      entry.status.classList.add('done')
    }
    if (toolGroup) {
      toolGroup.returned += 1
      state.toolDone += 1
      if (failed) {
        toolGroup.failed += 1
        toolGroup.row.classList.add('failed')
        // 失败也只改标题状态，默认保持折叠；用户点开看具体错误
      }
      updateToolGroup()
      if (toolGroup.returned >= toolGroup.count) markPhase('waiting')
    }
  } else {
    const row = document.createElement('div')
    row.className = 'errorRow'
    row.innerHTML = '<span class="errorDot"></span><span class="errorText"></span><span class="errorCode"></span>'
    row.querySelector('.errorText').textContent = `[${name || '工具'}] ${content}`
    addFlow(row)
  }
  state.chars += String(content || '').length
  updateStats()
  scrollToBottom()
}

/* ---------- 错误 ---------- */
function addError(message, label = '错误', codeText = '') {
  endAssistant()

  const details = document.createElement('details')
  details.className = 'errorDetails'

  const failLabel = document.createElement('summary')
  failLabel.className = 'failLabel'
  failLabel.textContent = label === '错误' ? '本轮运行失败' : label
  if (codeText) failLabel.textContent += ` · ${codeText}`
  details.appendChild(failLabel)

  const row = document.createElement('div')
  row.className = 'errorRow'
  const dot = document.createElement('span')
  dot.className = 'errorDot'
  const text = document.createElement('div')
  text.className = 'errorText'
  text.textContent = message
  row.appendChild(dot)
  row.appendChild(text)
  details.appendChild(row)

  addFlow(details)
  scrollToBottom(true)
}

/* ---------- 审批 ---------- */
const approvalCards = new Map()

function addApprovalRequest(ev) {
  const card = document.createElement('div')
  card.className = 'approvalCard'

  const isAccess = ev.kind === 'access'
  const title = document.createElement('div')
  title.className = 'approvalTitle'
  title.textContent = isAccess ? '需要访问工作区外的路径' : '需要你的许可'
  if (ev.background) {
    title.textContent += ` · 来自「${ev.session_title || '另一个会话'}」`
  }

  const tool = document.createElement('div')
  tool.className = 'approvalTool'
  tool.textContent = isAccess ? (ev.path || ev.name || '路径') : (ev.name || '能力调用')

  const args = document.createElement('pre')
  args.className = 'approvalArgs'
  args.textContent = isAccess
    ? (ev.reason || '该路径不在工作区 / 可访问路径里')
    : formatArgs(ev.arguments)
  args.hidden = isAccess && !ev.reason

  const hint = document.createElement('div')
  hint.className = 'approvalHint'
  hint.textContent = isAccess
    ? '允许 = 仅本次访问；想长期允许，请在「范围 → 可访问的路径」里添加'
    : ev.untrusted
      ? '这次调用发生在不可信内容之后，请确认来源可信'
      : ev.access === 'readonly'
        ? '当前范围是查看：写类调用会被拒绝'
        : '当前是询问模式：写文件 / 执行命令 / 外部调用需要确认'

  const actions = document.createElement('div')
  actions.className = 'approvalActions'
  const allow = document.createElement('button')
  allow.className = 'approve'
  allow.textContent = isAccess ? '允许本次' : '允许'
  const deny = document.createElement('button')
  deny.textContent = '拒绝'
  allow.addEventListener('click', () => decideApproval(ev.id, true, card))
  deny.addEventListener('click', () => decideApproval(ev.id, false, card))
  actions.appendChild(deny)
  if (isAccess) {
    const remember = document.createElement('button')
    remember.className = 'ghost'
    remember.textContent = '本次运行都允许'
    remember.addEventListener('click', () => decideApproval(ev.id, true, card, true))
    actions.appendChild(remember)
  }
  actions.appendChild(allow)

  const status = document.createElement('div')
  status.className = 'approvalStatus'
  status.hidden = true

  card.appendChild(title)
  card.appendChild(tool)
  card.appendChild(args)
  // 审批卡要“找得到”：滚动到可见 + 焦点落在「允许」，回车即可答复

  if (ev.untrusted) {
    const warning = document.createElement('div')
    warning.className = 'approvalWarning'
    warning.textContent = `⚠ 上一条工具结果来自不可信来源${ev.source ? `（${ev.source}）` : ''}，这次调用可能是提示注入诱导`
    card.appendChild(warning)
  }
  card.appendChild(hint)
  card.appendChild(actions)
  card.appendChild(status)
  addFlow(card)
  approvalCards.set(ev.id, card)
  card.scrollIntoView({ block: 'nearest' })
  allow.focus()
  scrollToBottom(true)
}

async function decideApproval(id, allow, card, remember = false) {
  const actions = card.querySelector('.approvalActions')
  if (actions) for (const button of actions.querySelectorAll('button')) button.disabled = true
  try {
    const res = await fetch('/api/approval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, allow, remember }),
    }).then((r) => r.json())
    if (!res.ok) {
      setApprovalResolved(card, allow, res.error || '请求已失效')
      return
    }
    setApprovalResolved(card, allow, allow ? '已允许' : '已拒绝')
  } catch {
    setApprovalResolved(card, false, '答复失败')
  }
}

function setApprovalResolved(card, allow, reason) {
  card.dataset.resolved = allow ? 'allow' : 'deny'
  const actions = card.querySelector('.approvalActions')
  if (actions) actions.remove()
  const status = card.querySelector('.approvalStatus')
  if (status) {
    status.hidden = false
    status.textContent = allow ? '✓ 已允许' : `✕ ${reason || '已拒绝'}`
  }
}

function resolveApproval(id, allow, reason) {
  const card = approvalCards.get(id)
  if (!card) return
  approvalCards.delete(id)
  setApprovalResolved(card, allow, reason)
}

/* ---------- 事件 ---------- */
function handleEvent(ev, replay = false) {
  const eventSession = ev.session || 'primary'
  const activeSession = state.sessionId || 'primary'
  if (!replay && eventSession !== activeSession) {
    // 后台会话的审批不能丢：切到那个会话再显示卡片；其他事件留给回放
    if (ev.type === 'approval_request') {
      toast(`「${ev.session_title || '另一个会话'}」需要审批`)
      switchSessionById(eventSession)
        .then(() => addApprovalRequest(ev))
        .catch(() => addApprovalRequest({ ...ev, background: true }))
    }
    return
  }
  switch (ev.type) {
    case 'user_message':
      // 新用户消息 = 新轮次：让上一轮遗留的 idle 定时器立即失效
      clearTimeout(state.idleTimer)
      state.idleTimer = 0
      state.turnToken += 1
      resetTurnBodies()
      addUser(ev.text, (ev.images || []).map((item) => imageSrc(item.url)))
      if (replay) {
        state.turns += 1
        const head = document.createElement('div')
        head.className = 'turnHead'
        head.dataset.done = '1'
        head.innerHTML = '<span class="caret"></span><span>已完成</span>'
        addFlow(head)
      }
      break
    case 'assistant_delta':
      pushDelta(ev.text)
      break
    case 'assistant_message':
      state.thinkingNow = false
      if (!replay) {
        const now = performance.now()
        if (!state.firstTokenAt) state.firstTokenAt = now
        state.lastTokenAt = now
      }
      addAssistantMessage(ev.text)
      state.chars += String(ev.text || '').length
      updateStats()
      break
    case 'assistant_final':
      applyAssistantFinal(ev.text)
      break
    case 'assistant_end':
      endAssistant()
      if (!replay) scheduleIdle()
      loadUsage()
      break
    case 'usage':
      loadUsage()
      loadContext()
      break
    case 'reasoning_delta':
      pushReasoningDelta(ev.text)
      break
    case 'reasoning_end':
      endReasoning()
      break
    case 'reasoning':
      addReasoning(ev.text)
      break
    case 'tool_call':
      activity()
      addToolCall(ev.name, ev.arguments, ev.call_id)
      break
    case 'tool_result':
      activity()
      addToolResult(ev.name, ev.content, ev.call_id)
      break
    case 'tool_delta':
      activity()
      appendToolDelta(ev.call_id, ev.text)
      break
    case 'approval_request':
      activity()
      addApprovalRequest(ev)
      break
    case 'approval_resolved':
      resolveApproval(ev.id, ev.allow, ev.reason)
      break
    case 'error':
      addError(ev.message, '错误')
      finishTurn(true, state.turnToken)
      break
    case 'exception': {
      const message = `${ev.system ? '[' + ev.system + '] ' : ''}${ev.where || ''} ${ev.kind || ''} ${ev.message || ''}`.trim()
      if (ev.where === 'max_steps') {
        addError(message, '工具步数达到上限')
      } else {
        addError(message, '异常', ev.where || ev.kind || '')
      }
      finishTurn(true, state.turnToken)
      break
    }
    case 'engine_end':
      finishTurn(true, state.turnToken)
      addError('计算机已停机', '错误')
      break
  }
}

const es = new EventSource(API_TOKEN ? `/api/events?token=${encodeURIComponent(API_TOKEN)}` : '/api/events')
es.onmessage = (event) => {
  try {
    handleEvent(JSON.parse(event.data))
  } catch { /* 忽略坏事件 */ }
}
// EventSource 断线会自动重连，但重连期间的事件不会补：重连成功后拉一次历史对齐
let esOpened = false
es.onopen = () => {
  if (esOpened && !state.running) loadHistory()
  esOpened = true
}

/* ---------- 侧栏宽度（可拖动） ---------- */
const SIDEBAR_KEY = 'spirit.sidebarWidth'
const SIDEBAR_DEFAULT = 258

function applySidebarWidth(width) {
  const clamped = Math.max(200, Math.min(460, Math.round(width)))
  document.documentElement.style.setProperty('--spirit-sidebar-width', `${clamped}px`)
  return clamped
}

const savedSidebar = Number(localStorage.getItem(SIDEBAR_KEY) || 0)
if (savedSidebar) applySidebarWidth(savedSidebar)

let sidebarDragging = false
sidebarResizer.addEventListener('pointerdown', (event) => {
  sidebarDragging = true
  sidebarResizer.setPointerCapture(event.pointerId)
  document.body.classList.add('resizing-sidebar')
})
window.addEventListener('pointermove', (event) => {
  if (!sidebarDragging) return
  applySidebarWidth(event.clientX)
})
function stopSidebarDrag() {
  if (!sidebarDragging) return
  sidebarDragging = false
  document.body.classList.remove('resizing-sidebar')
  const width = parseInt(
    getComputedStyle(document.documentElement).getPropertyValue('--spirit-sidebar-width'),
    10,
  ) || SIDEBAR_DEFAULT
  localStorage.setItem(SIDEBAR_KEY, String(width))
}
window.addEventListener('pointerup', stopSidebarDrag)
window.addEventListener('pointercancel', stopSidebarDrag)
sidebarResizer.addEventListener('dblclick', () => {
  applySidebarWidth(SIDEBAR_DEFAULT)
  localStorage.removeItem(SIDEBAR_KEY)
})

/* ---------- 会话 ---------- */
function relativeTime(mtime) {
  const minutes = Math.max(0, Math.round((Date.now() / 1000 - mtime) / 60))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}小时`
  return `${Math.round(hours / 24)}天`
}

async function loadSessions() {
  try {
    const items = await fetch('/api/sessions').then((res) => res.json())
    sessionList.innerHTML = ''
    for (const item of items) {
      const btn = document.createElement('button')
      btn.className = 'session-item'
      btn.dataset.session = item.session || ''
      btn.dataset.path = item.path || ''
      btn.dataset.title = item.title
      const title = document.createElement('span')
      title.className = 'title'
      title.textContent = item.title + (item.running ? ' · 运行中' : '')
      const time = document.createElement('span')
      time.className = 'time'
      time.textContent = item.mtime ? relativeTime(item.mtime) : ''
      const more = document.createElement('button')
      more.className = 'session-more'
      more.title = '更多'
      more.textContent = '⋯'
      more.addEventListener('click', (event) => {
        event.stopPropagation()
        openSessionMenu(more, item)
      })
      btn.appendChild(title)
      btn.appendChild(time)
      // 还没落盘的运行中会话没有文件，改名 / 删除先不给
      if (item.path) btn.appendChild(more)
      btn.addEventListener('click', () => {
        if (item.live && item.session) switchSessionById(item.session)
        else if (item.path) switchSession(item.path)
      })
      sessionList.appendChild(btn)
    }
    filterSessions()
    markActive(state.sessionId)
  } catch { /* 无会话 */ }
}

function filterSessions() {
  const needle = sessionSearch.value.trim().toLowerCase()
  for (const item of sessionList.querySelectorAll('.session-item')) {
    const title = item.dataset.title || ''
    item.style.display = !needle || title.toLowerCase().includes(needle) ? '' : 'none'
  }
}

function markActive(sessionId) {
  for (const el of sessionList.querySelectorAll('.session-item')) {
    el.classList.toggle('active', !!sessionId && el.dataset.session === sessionId)
  }
}

async function refreshSessions() {
  await loadSessions()
}

async function refreshStatus() {
  try {
    const status = await fetch('/api/status').then((res) => res.json())
    if (status.session && status.session !== state.currentSession) {
      state.currentSession = status.session
      markActive(state.sessionId)
    }
  } catch { /* 忽略 */ }
}

/* 显示线程运行期健康：停了就常驻提示，刷新页面可回放（history 不依赖线程） */
let renderWarned = false

async function checkRenderHealth() {
  try {
    const status = await fetch('/api/status').then((res) => res.json())
    const render = status.render || {}
    const bad = render.alive === false || render.healthy === false
    if (bad) {
      const reason = render.alive === false ? '已停止' : '异常'
      const detail = String(render.error || '').slice(0, 120)
      renderWarnEl.textContent = `显示线程${reason}，刷新页面可回放${detail ? `：${detail}` : ''}`
      renderWarnEl.hidden = false
      renderWarned = true
    } else if (renderWarned) {
      renderWarnEl.hidden = true
      renderWarned = false
    }
  } catch { /* 引擎未起 */ }
}

let sessionMenu = null

function closeSessionMenu() {
  if (sessionMenu) {
    sessionMenu.remove()
    sessionMenu = null
  }
}

function openSessionMenu(anchor, item) {
  closeSessionMenu()
  const rect = anchor.getBoundingClientRect()
  const menu = document.createElement('div')
  menu.className = 'session-menu'
  menu.style.left = `${Math.max(8, rect.left - 120)}px`
  menu.style.top = `${rect.bottom + 4}px`

  const rename = document.createElement('button')
  rename.textContent = '重命名'
  rename.addEventListener('click', async () => {
    closeSessionMenu()
    const title = window.prompt('新标题', item.title)
    if (!title || !title.trim()) return
    const res = await fetch('/api/session/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: item.path, title: title.trim() }),
    }).then((r) => r.json())
    if (res.ok) {
      toast('已重命名')
      if (state.currentSession === item.path) setTitle(res.title)
      await loadSessions()
    } else {
      toast(res.error || '重命名失败')
    }
  })

  const remove = document.createElement('button')
  remove.textContent = '删除'
  remove.addEventListener('click', async () => {
    closeSessionMenu()
    if (!window.confirm(`删除会话「${item.title}」？`)) return
    const res = await fetch('/api/session/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: item.path }),
    }).then((r) => r.json())
    if (res.ok) {
      toast('已删除')
      if (state.currentSession === item.path || item.session === state.sessionId) {
        state.sessionId = 'primary'
        state.currentSession = null
        resetView()
        setTitle('会话')
        await loadHistory()      // 删的是当前会话 → 回到主会话
        await loadScenarios()
      }
      await loadSessions()
    } else {
      toast(res.error || '删除失败')
    }
  })

  menu.appendChild(rename)
  menu.appendChild(remove)
  document.body.appendChild(menu)
  sessionMenu = menu
}

function resetView() {
  leaveTurn()
  column.innerHTML = ''
  turnRail.innerHTML = ''
  toolGroup = null
  state.turnTop = null
  toolRows.length = 0
  toolRowsById.clear()
  assistant = null
  lastAssistant = null
  reasoning = null
  reasoningBlock = null
  state.assistantSpoken = false
  state.turnHasMeta = false
  turnMeta = null
  turnDivider = null
  state.turns = 0
  state.steps = 0
  state.chars = 0
  state.rate = 0
  state.firstTokenAt = 0
  state.lastTokenAt = 0
  state.turnElapsed = 0
  state.ttftSum = 0
  state.ttftCount = 0
  state.tps = 0
  state.turnHead = null
  state.turnBodies = []
  state.turnProcess = null
  state.turnProcessCount = 0
  state.currentSession = null
  for (const entry of toolRows) {
    if (entry.status) {
      entry.status.textContent = userStopped ? '已中断' : '未返回'
      entry.status.classList.add('done')
    }
  }
  toolRows.length = 0
  toolRowsById.clear()

  state.running = false
  updateSendButton()
  shell.classList.add('hero')
  updateStats()
}

function renderHistory(events, meta = {}) {
  column.innerHTML = ''
  resetTurnBodies()
  turnRail.innerHTML = ''
  toolGroup = null
  state.turnTop = null
  toolRows.length = 0
  toolRowsById.clear()
  assistant = null
  lastAssistant = null
  reasoning = null
  reasoningBlock = null
  state.assistantSpoken = false
  state.turnHasMeta = false
  turnMeta = null
  turnDivider = null
  state.turns = 0
  state.steps = 0
  state.chars = 0
  state.rate = 0
  state.firstTokenAt = 0
  state.lastTokenAt = 0
  state.turnElapsed = 0
  state.ttftSum = 0
  state.ttftCount = 0
  state.tps = 0
  state.turnHead = null
  if (meta.has_more) {
    const wrap = document.createElement('div')
    wrap.className = 'loadOlderRow'
    const more = document.createElement('button')
    more.className = 'ghost-btn mini'
    more.textContent = '加载更早'
    more.addEventListener('click', loadOlderHistory)
    wrap.appendChild(more)
    column.appendChild(wrap)
  }
  shell.classList.toggle('hero', !events.length && !meta.has_more)
  for (const ev of events) handleEvent(ev, true)
  // 回放的历史轮次全部默认收起（失败的也在标题上标出）
  for (const group of column.querySelectorAll('.toolGroup')) {
    group.open = false
  }
  updateStats()
  scrollToBottom(true)
}

async function loadHistory() {
  try {
    const data = await fetch(sessionUrl(`/api/history?limit=${state.historyLimit}`))
      .then((res) => res.json())
    renderHistory(data.events || [], data)
  } catch { /* 无历史 */ }
}

async function loadOlderHistory() {
  state.historyLimit = Math.min(500, (state.historyLimit || 40) + 40)
  await loadHistory()
}

async function switchSession(path, btn) {
  try {
    const data = await fetch('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }).then((res) => res.json())
    if (!data.ok) {
      toast(data.error || '这一轮还在处理，等结束再切换')
      return
    }
    leaveTurn()
    state.currentSession = path
    state.sessionId = data.session || 'primary'
    state.historyLimit = 40
    renderHistory(data.events || [], data)
    setTitle(data.title)
    markActive(state.sessionId)
    await loadSessions()    // 刚打开的会话会变成运行中条目，侧栏要跟上
    if (data.warnings?.length) toast(data.warnings[0])
    await loadScenarios()   // 场景跟着会话走（会话里是什么就是什么）
    await loadSettings()
  } catch { /* 忽略 */ }
}

async function switchSessionById(id) {
  const data = await fetch('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: id }),
  }).then((r) => r.json())
  if (!data.ok) throw new Error(data.error || '切换失败')
  leaveTurn()
  state.sessionId = data.session || id
  const items = await fetch('/api/sessions').then((r) => r.json()).catch(() => [])
  const item = items.find((entry) => (entry.session || 'primary') === state.sessionId)
  state.currentSession = item?.path || null
  state.historyLimit = 40
  renderHistory(data.events || [], data)
  setTitle(data.title || '会话')
  markActive(state.sessionId)
}

async function newSession() {
  try {
    const data = await fetch('/api/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new: true, session: state.sessionId }),
    }).then((res) => res.json())
    if (!data.ok) {
      toast(data.error || '这一轮还在处理，等结束再新建')
      return
    }
    resetView()
    state.sessionId = data.session || 'primary'
    setTitle('新会话')
    markActive(state.sessionId)
    await loadScenarios()   // 新会话：场景解锁，可以重新选
    await loadSessions()
    await loadUsage()
    await loadContext()
  } catch { /* 忽略 */ }
}

/* ---------- 轨迹 ---------- */
const TRAIL_KIND = {
  user_message: '用户',
  assistant_message: '助手',
  reasoning: '思考',
  tool_call: '工具',
  tool_result: '结果',
  error: '错误',
}

async function showTrajectory() {
  let events = []
  try {
    const data = await fetch('/api/history?limit=200').then((res) => res.json())
    events = data.events || []
  } catch { /* 无历史 */ }
  trajectory.innerHTML = ''
  if (state.lastBreakdown) {
    const row = document.createElement('div')
    row.className = 't-item'
    const kind = document.createElement('div')
    kind.className = 't-kind'
    kind.textContent = '耗时'
    const main = document.createElement('div')
    main.className = 't-main'
    main.textContent = state.lastBreakdown
    row.appendChild(kind)
    row.appendChild(main)
    trajectory.appendChild(row)
  }
  for (const ev of events) {
    const label = TRAIL_KIND[ev.type]
    if (!label) continue
    const row = document.createElement('div')
    row.className = 't-item'
    const kind = document.createElement('div')
    kind.className = 't-kind'
    kind.textContent = label
    const main = document.createElement('div')
    main.className = 't-main'
    let text = ev.text || ev.message || ''
    if (ev.type === 'tool_call') text = `${ev.name} ${ev.arguments || ''}`
    if (ev.type === 'tool_result') text = `${ev.name || ''}：${ev.content || ''}`
    main.textContent = String(text).slice(0, 600)
    row.appendChild(kind)
    row.appendChild(main)
    trajectory.appendChild(row)
  }
  if (!events.length) {
    const empty = document.createElement('div')
    empty.className = 't-main'
    empty.textContent = '当前会话还没有记录。'
    trajectory.appendChild(empty)
  }
  state.view = 'trail'
  trajectory.hidden = false
  transcript.hidden = true
  turnRail.style.display = 'none'
  document.getElementById('tabTrail').classList.add('active')
  document.getElementById('tabChat').classList.remove('active')
}

function showChat() {
  state.view = 'chat'
  trajectory.hidden = true
  transcript.hidden = false
  turnRail.style.display = ''
  document.getElementById('tabChat').classList.add('active')
  document.getElementById('tabTrail').classList.remove('active')
}

/* ---------- 设置 / 模型 ---------- */
function markSegmented(container, value) {
  for (const b of container.querySelectorAll('button')) {
    b.classList.toggle('active', b.dataset.value === String(value))
  }
}

const APPROVAL_LABEL = {
  ask: '询问',
  auto: '⏵⏵ 自动',
}
const ACCESS_LABEL = {
  workspace: '可修改',
  readonly: '查看',
}
const APPROVAL_LEGACY = { manual: 'ask', rules: 'ask', auto: 'auto' }

function normalizeApproval(value) {
  const mode = APPROVAL_LEGACY[value] || value
  return APPROVAL_LABEL[mode] ? mode : 'ask'
}

function syncModelUI() {
  const label = EFFORT_LABEL[state.effort] || 'High'
  const model = state.model || 'deepseek-Flash'
  modelPillText.textContent = `${model} ${label}`
  popModelValue.textContent = model
  popEffortValue.textContent = label
  settingSessions.textContent = state.sessionDir || '—'
  approvalLabel.textContent = APPROVAL_LABEL[state.approval] || APPROVAL_LABEL.ask
  accessLabel.textContent = ACCESS_LABEL[state.access] || ACCESS_LABEL.workspace
  if (outsideAutoState) {
    outsideAutoState.textContent = state.outsideAuto ? '自动允许' : '仅工作区'
  }
  if (accessHint) {
    accessHint.textContent = state.outsideAuto
      ? '查看：写文件 / 执行命令直接拒绝；可修改：允许改，工作区外也能访问'
      : '查看：写文件 / 执行命令直接拒绝；可修改：允许改，工作区外越界会弹授权'
  }
  autoHint.hidden = state.approval !== 'auto'
  for (const button of accessPop.querySelectorAll('button[data-access]')) {
    button.classList.toggle('active', button.dataset.access === state.access)
  }
  const current = state.scenarios.find((item) => item.id === state.scenario)
  scenarioLabel.textContent = current?.name
    || (state.scenario === 'pentest' ? '渗透' : '日常')
  updateScopeUI()
  for (const button of approvalPop.querySelectorAll('button[data-mode]')) {
    button.classList.toggle('active', button.dataset.mode === state.approval)
  }
  markSegmented(effortSeg, state.effort)
  markSegmented(untrustedSeg, state.untrusted)
  thinkingSwitch.setAttribute('aria-checked', state.thinking ? 'true' : 'false')
  if (popThinkingSwitch) {
    popThinkingSwitch.setAttribute('aria-checked', state.thinking ? 'true' : 'false')
  }
  failoverSwitch.setAttribute('aria-checked', state.failover ? 'true' : 'false')
}

async function loadBrowserStatus() {
  if (!browserStatus) return
  browserStatus.textContent = '检查中…'
  try {
    const data = await fetch(sessionUrl('/api/browser')).then((res) => res.json())
    if (!data.ok) {
      browserStatus.textContent = '引擎未启动'
      return
    }
    const parts = []
    if (!data.installed) {
      parts.push('未安装 ego lite')
    } else {
      parts.push(data.onboarded === false ? '已安装，未完成初始化'
        : data.onboarded ? '已就绪' : '已安装')
      parts.push(data.running ? '应用运行中' : '应用未运行')
    }
    if (data.attention === 'permission') {
      parts.push('等待你在浏览器里处理权限弹窗')
    }
    if (data.space?.space) {
      parts.push(`Space ${data.space.space} · ${data.space.pages} 页`)
      if (data.space.title) parts.push(data.space.title)
    } else if (data.space?.error) {
      parts.push('页面状态读取失败')
    }
    browserStatus.textContent = parts.join(' · ')
    browserPath.textContent = data.path || '—'
    browserPath.title = data.path || ''
  } catch {
    browserStatus.textContent = '检查失败'
  }
}

async function loadSettings() {
  try {
    const data = await fetch('/api/settings').then((res) => res.json())
    state.thinking = !!data.thinking
    state.effort = normalizeEffort(data.effort)
    state.model = data.model || 'deepseek-Flash'
    state.workdir = data.workdir || ''
    state.approval = normalizeApproval(data.approval)
    state.access = ACCESS_LABEL[data.access] ? data.access : 'workspace'
    state.outsideAuto = data.sandbox_workspace === false || !!data.auto_allow_outside
    state.untrusted = ['warn', 'confirm', 'block'].includes(data.untrusted_policy)
      ? data.untrusted_policy
      : 'confirm'
    state.scenario = data.scenario || state.scenario
    applyScenarioTheme()
    state.sessionDir = data.session_dir || state.sessionDir
    state.configPath = data.config_path || state.configPath
    state.providerId = data.provider_id || state.providerId
    state.build = data.build || ''
    state.failover = !!data.failover
    state.limits = {
      turn: Number(data.max_turn_tokens || 0),
      session: Number(data.max_session_tokens || 0),
      repeat: Number(data.repeat_limit ?? 3),
    }
    limitTurnTokens.value = state.limits.turn || ''
    limitSessionTokens.value = state.limits.session || ''
    repeatLimit.value = state.limits.repeat
    state.contextWindow = Number(data.context_window || 128000)
    syncModelUI()
  } catch { /* 默认 */ }
}

async function saveLimits() {
  state.limits = {
    turn: Math.max(0, Number(limitTurnTokens.value) || 0),
    session: Math.max(0, Number(limitSessionTokens.value) || 0),
    repeat: Math.max(0, Number(repeatLimit.value) || 0),
  }
  await saveSetting({
    max_turn_tokens: state.limits.turn,
    max_session_tokens: state.limits.session,
    repeat_limit: state.limits.repeat,
  })
  updateStats()
  toast('预算已保存')
}

async function saveSetting(payload) {
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  } catch { /* 忽略 */ }
}

function setEffort(value) {
  state.effort = value
  syncModelUI()
  saveSetting({ effort: state.effort, thinking: state.thinking })
}

function toggleThinking() {
  state.thinking = !state.thinking
  syncModelUI()
  saveSetting({ thinking: state.thinking, effort: state.effort })
}

/* ---------- 模型提供商 ---------- */
function providerById(id) {
  return state.providers.find((item) => item.id === id)
}

function providerStatus(provider) {
  if (provider.from_env) return '密钥来自环境变量'
  if (provider.has_key) return `已配置密钥 · …${provider.key_hint || ''}`
  return '未配置密钥'
}

function providerKindLabel(kind) {
  if (kind === 'anthropic') return 'Anthropic'
  return kind === 'openai-chat' ? 'Chat' : 'Responses'
}

/* 图标来自 cc-switch（MIT）src/icons/extracted；找不到就退回首字色块 */
function presetFor(provider) {
  const base = String(provider.base_url || '').replace(/\/+$/, '').toLowerCase()
  const byBase = base
    ? PROVIDER_PRESETS.find(
      (preset) => preset.base_url && preset.base_url.replace(/\/+$/, '').toLowerCase() === base,
    )
    : null
  if (byBase) return byBase
  const name = String(provider.name || '').trim().toLowerCase()
  return PROVIDER_PRESETS.find((preset) => preset.name.toLowerCase() === name) || null
}

function logoNode(preset, name, color) {
  const logo = document.createElement('span')
  logo.className = 'provider-logo'
  if (preset?.icon_file) {
    logo.classList.add('has-icon')
    const image = document.createElement('img')
    image.src = `/static/provider-icons/${preset.icon_file}`
    image.alt = ''
    image.loading = 'lazy'
    image.addEventListener('error', () => {
      image.remove()
      logo.classList.remove('has-icon')
      logo.textContent = String(name || '?').slice(0, 1)
      logo.style.background = color || preset.color || '#9ca3af'
    })
    logo.appendChild(image)
  } else {
    logo.textContent = String(name || '?').slice(0, 1)
    logo.style.background = color || preset?.color || '#9ca3af'
  }
  return logo
}

function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return String(url || '')
  }
}

async function loadProviders() {
  try {
    const data = await fetch('/api/providers').then((res) => res.json())
    state.providers = data.providers || []
    state.providerId = data.active || state.providerId
    if (data.model) state.model = data.model
    renderProviders()
    renderModelOptions()
    syncModelUI()
  } catch { /* 引擎未起 */ }
}

function providerMatches(provider, query) {
  if (!query) return true
  const preset = presetFor(provider)
  const text = [
    provider.name, provider.notes, provider.website, provider.base_url,
    provider.category_label, preset?.domain, preset?.desc,
    (provider.models || []).join(' '),
  ].join(' ').toLowerCase()
  return query.split(/\s+/).every((part) => !part || text.includes(part))
}

function providerLogoSpan(provider, preset) {
  const logo = document.createElement('span')
  const iconFile = provider.icon || preset?.icon_file
  if (iconFile) {
    logo.className = 'provider-logo has-icon'
    const image = document.createElement('img')
    image.src = `/static/provider-icons/${iconFile}`
    image.alt = ''
    image.onerror = () => { image.remove() }
    logo.appendChild(image)
  } else {
    logo.className = 'provider-logo'
    logo.style.background = provider.icon_color || preset?.color || '#9ca3af'
    logo.textContent = (provider.name || '?').trim().charAt(0).toUpperCase()
  }
  return logo
}

function healthText(health) {
  if (!health) return null
  if (!health.reachable) return { text: '不可达', cls: 'failed' }
  const seconds = (health.latency_ms / 1000).toFixed(1)
  if (health.level === 'degraded') return { text: `较慢 ${seconds}s`, cls: 'degraded' }
  return { text: `可达 ${health.latency_ms}ms`, cls: 'ok' }
}

function balanceText(balance) {
  if (!balance || !balance.ok) return null
  const first = (balance.items || [])[0]
  if (!first) return null
  const amount = first.remaining ?? first.total
  if (amount === null || amount === undefined) return null
  const symbol = first.unit === 'USD' ? '$' : '¥'
  return `${symbol}${Number(amount).toFixed(2)}`
}

function renderProviders() {
  providerList.innerHTML = ''
  const query = state.providerSearch.trim().toLowerCase()
  const shown = state.providers.filter((provider) => providerMatches(provider, query))

  if (!shown.length) {
    const empty = document.createElement('div')
    empty.className = 'provider-empty'
    empty.textContent = query ? '没有匹配的供应商。' : '还没有配置供应商。'
    providerList.appendChild(empty)
    return
  }

  for (const provider of shown) {
    const preset = presetFor(provider)
    const row = document.createElement('div')
    row.className = 'provider-row' + (provider.active ? ' active' : '')
    row.dataset.id = provider.id
    // 搜索过滤时不支持拖拽（拖出来的顺序会和列表对不上）
    if (!query) {
      row.draggable = true
      row.addEventListener('dragstart', (event) => {
        state.dragId = provider.id
        row.classList.add('dragging')
        event.dataTransfer?.setData('text/plain', provider.id)
        if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
      })
      row.addEventListener('dragend', () => {
        state.dragId = ''
        for (const item of providerList.children) item.classList.remove('dragging', 'drag-over')
      })
      row.addEventListener('dragover', (event) => {
        if (!state.dragId || state.dragId === provider.id) return
        event.preventDefault()
        row.classList.add('drag-over')
      })
      row.addEventListener('dragleave', () => row.classList.remove('drag-over'))
      row.addEventListener('drop', (event) => {
        event.preventDefault()
        row.classList.remove('drag-over')
        const from = state.dragId
        const to = provider.id
        state.dragId = ''
        if (!from || from === to) return
        reorderProviders(from, to)
      })
    }

    const main = document.createElement('div')
    main.className = 'provider-main'
    if (!query) {
      const handle = document.createElement('span')
      handle.className = 'provider-drag'
      handle.textContent = '⋮⋮'
      handle.title = '拖动排序'
      main.appendChild(handle)
    }
    main.appendChild(providerLogoSpan(provider, preset))

    const info = document.createElement('div')
    info.className = 'provider-info'
    const name = document.createElement('div')
    name.className = 'provider-name'
    name.textContent = provider.name
    const url = document.createElement('div')
    url.className = 'provider-url'
    url.textContent = provider.notes || hostOf(provider.website || preset?.website || provider.base_url)
    info.append(name, url)

    const meta = document.createElement('div')
    meta.className = 'provider-meta'
    const kind = document.createElement('span')
    kind.className = 'provider-kind'
    kind.textContent = providerKindLabel(provider.kind)
    meta.appendChild(kind)
    if (provider.category && provider.category !== 'custom') {
      const chip = document.createElement('span')
      chip.className = 'provider-chip'
      chip.textContent = provider.category_label || provider.category
      meta.appendChild(chip)
    }
    const priority = state.providers
      .filter((item) => item.in_failover_queue)
      .findIndex((item) => item.id === provider.id)
    if (priority >= 0) {
      const chip = document.createElement('span')
      chip.className = 'provider-chip priority'
      chip.textContent = `P${priority + 1}`
      chip.title = '故障转移优先级（按列表顺序）'
      meta.appendChild(chip)
    }
    const status = document.createElement('span')
    status.className = 'provider-status'
    status.textContent = providerStatus(provider)
    meta.appendChild(status)
    const health = healthText(state.health[provider.id])
    if (health) {
      const badge = document.createElement('span')
      badge.className = `provider-health ${health.cls}`
      badge.textContent = health.text
      meta.appendChild(badge)
    }
    const balance = balanceText(state.balance[provider.id])
    if (balance) {
      const money = document.createElement('span')
      money.className = 'provider-balance'
      money.textContent = `余额 ${balance}`
      meta.appendChild(money)
    }
    info.appendChild(meta)
    main.appendChild(info)

    const actions = document.createElement('div')
    actions.className = 'provider-actions'
    if (provider.active) {
      const badge = document.createElement('span')
      badge.className = 'provider-badge'
      badge.textContent = '使用中 · ' + state.model
      actions.appendChild(badge)
    } else {
      const use = document.createElement('button')
      use.className = 'ghost-btn mini'
      use.textContent = '设为当前'
      use.addEventListener('click', () => activateProvider(provider.id))
      actions.appendChild(use)
    }
    const check = document.createElement('button')
    check.className = 'ghost-btn mini'
    check.textContent = '测试'
    check.addEventListener('click', () => checkProvider(provider.id))
    actions.appendChild(check)
    const money = document.createElement('button')
    money.className = 'ghost-btn mini'
    money.textContent = '余额'
    money.addEventListener('click', () => queryBalance(provider.id))
    actions.appendChild(money)
    const copy = document.createElement('button')
    copy.className = 'ghost-btn mini'
    copy.textContent = '复制'
    copy.addEventListener('click', () => duplicateProvider(provider.id))
    actions.appendChild(copy)
    const edit = document.createElement('button')
    edit.className = 'ghost-btn mini'
    edit.textContent = '编辑'
    edit.addEventListener('click', () => openProviderForm(provider.id))
    actions.appendChild(edit)

    row.appendChild(main)
    row.appendChild(actions)
    providerList.appendChild(row)
  }
}

async function reorderProviders(fromId, toId) {
  const ids = state.providers.map((provider) => provider.id)
  const from = ids.indexOf(fromId)
  const to = ids.indexOf(toId)
  if (from < 0 || to < 0) return
  ids.splice(to, 0, ids.splice(from, 1)[0])
  const res = await fetch('/api/provider/reorder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '排序失败')
    return
  }
  state.providers = res.providers || state.providers
  renderProviders()
}

async function checkProvider(id) {
  toast('正在测试连接…')
  const res = await fetch('/api/provider/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '测试失败')
    return
  }
  state.health[id] = res
  renderProviders()
  const hops = res.redirects ? `，经 ${res.redirects} 次跳转` : ''
  if (!res.reachable) toast(`不可达：${res.error}`)
  else if (res.level === 'degraded') toast(`可达但较慢（${res.latency_ms}ms）`)
  else toast(`可达 · ${res.latency_ms}ms`)
}

async function queryBalance(id) {
  toast('正在查余额…')
  const res = await fetch('/api/provider/balance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '余额查询失败')
    return
  }
  state.balance[id] = res
  renderProviders()
  if (!res.ok) {
    toast(res.error || '余额查询失败')
    return
  }
  const first = (res.items || [])[0]
  const amount = first?.remaining ?? first?.total
  const symbol = first?.unit === 'USD' ? '$' : '¥'
  toast(amount === null || amount === undefined
    ? `${res.provider?.name || '供应商'} 已返回余额`
    : `余额 ${symbol}${Number(amount).toFixed(2)}`)
}

function renderModelOptions() {
  popModelList.innerHTML = ''
  for (const provider of state.providers) {
    const models = provider.models || []
    if (!models.length) continue
    const group = document.createElement('div')
    group.className = 'model-group'
    group.textContent = provider.name + (provider.active ? ' · 使用中' : '')
    popModelList.appendChild(group)
    for (const model of models) {
      const option = document.createElement('button')
      option.className = 'pop-option'
        + (provider.active && model === state.model ? ' active' : '')
      option.textContent = model
      option.addEventListener('click', (event) => {
        event.stopPropagation()
        activateProvider(provider.id, model)
      })
      popModelList.appendChild(option)
    }
  }
  popModelList.hidden = !popModelList.children.length
}

/* ---------- 添加供应商：预设画廊（cc-switch 式：搜索 + 左侧分类 + 分组卡片） ---------- */
function presetMatches(preset, query, category) {
  if (category && category !== '全部' && preset.category !== category) return false
  if (!query) return true
  const text = [
    preset.name, preset.domain, preset.website, preset.base_url, preset.desc,
  ].join(' ').toLowerCase()
  return query.split(/\s+/).every((part) => !part || text.includes(part))
}

function presetCount(category, query) {
  return PROVIDER_PRESETS.filter((preset) => presetMatches(preset, query, category)).length
}

function renderPresetCategories() {
  const query = presetSearch.value.trim().toLowerCase()
  presetCats.innerHTML = ''
  for (const category of ['全部', ...PROVIDER_CATEGORIES]) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'preset-cat' + (state.presetCategory === category ? ' active' : '')
    const count = presetCount(category, query)
    const label = document.createElement('span')
    label.textContent = category
    const num = document.createElement('span')
    num.className = 'preset-cat-count'
    num.textContent = String(count)
    button.append(label, num)
    button.addEventListener('click', () => {
      state.presetCategory = category
      renderPresetCategories()
      renderPresetGrid()
      presetScroll.scrollTop = 0
    })
    presetCats.appendChild(button)
  }
}

// 预设画廊的分类是中文字段（照抄 cc-switch 的分组），表单里存的是枚举
function presetCategoryFor(preset) {
  switch (preset?.category) {
    case '账号登录': return 'official'
    case '模型厂商': return 'cn_official'
    case '第三方平台': return 'third_party'
    case '云服务商': return 'cloud_provider'
    default: return 'custom'
  }
}

function presetBadge(preset) {
  if (preset.oauth) return { text: '需要账号登录', warn: true }
  if (!preset.supported) return { text: '暂不支持', warn: true }
  if (preset.templated) return { text: '需填地址变量', warn: true }
  return { text: preset.models.length ? `${preset.models.length} 个模型` : providerKindLabel(preset.kind), warn: false }
}

function presetCard(preset) {
  const card = document.createElement('button')
  card.type = 'button'
  card.className = 'preset-card' + (preset.oauth || !preset.supported ? ' disabled' : '')
  card.append(logoNode(preset, preset.name))

  const meta = document.createElement('span')
  meta.className = 'preset-meta'
  const head = document.createElement('span')
  head.className = 'preset-name-row'
  const name = document.createElement('span')
  name.className = 'preset-name'
  name.textContent = preset.name
  head.appendChild(name)
  const badge = presetBadge(preset)
  if (badge.warn) {
    const mark = document.createElement('span')
    mark.className = 'preset-warn'
    mark.textContent = badge.text
    head.appendChild(mark)
  }
  const desc = document.createElement('div')
  desc.className = 'preset-desc'
  desc.textContent = preset.domain || hostOf(preset.base_url)
  meta.append(head, desc)
  if (!badge.warn) {
    const kind = document.createElement('span')
    kind.className = 'preset-kind'
    kind.textContent = badge.text
    meta.appendChild(kind)
  }
  card.appendChild(meta)

  card.addEventListener('click', () => {
    if (preset.oauth) {
      toast(`${preset.name} 需要账号登录（OAuth），Spirit 目前只支持 API Key`)
      return
    }
    if (!preset.supported) {
      toast(`${preset.name} 的接口格式（Gemini Native）暂不支持`)
      return
    }
    if (preset.templated) {
      toast('这个预设的地址里有变量（如 ${REGION}），打开后替换成实际值')
    }
    openProviderForm(null, preset)
  })
  return card
}

function renderPresetGrid() {
  const query = presetSearch.value.trim().toLowerCase()
  const category = state.presetCategory
  presetGrid.innerHTML = ''

  let any = false
  for (const group of PROVIDER_CATEGORIES) {
    if (category !== '全部' && category !== group) continue
    const items = PROVIDER_PRESETS.filter(
      (preset) => preset.category === group && presetMatches(preset, query, '全部'),
    )
    if (!items.length) continue
    any = true

    const section = document.createElement('section')
    section.className = 'preset-group'
    const title = document.createElement('div')
    title.className = 'preset-group-title'
    title.textContent = group
    const grid = document.createElement('div')
    grid.className = 'preset-grid'
    for (const preset of items) grid.appendChild(presetCard(preset))
    section.append(title, grid)
    presetGrid.appendChild(section)
  }

  if (!any) {
    const empty = document.createElement('div')
    empty.className = 'preset-empty'
    empty.textContent = '没有匹配的供应商，换个关键词，或用上面的“自定义配置”。'
    presetGrid.appendChild(empty)
  }
  presetCustom.hidden = !!query || category !== '全部'
}

function openPresetView() {
  state.preset = null
  state.presetCategory = '全部'
  presetSearch.value = ''
  providerListView.hidden = true
  providerForm.hidden = true
  presetView.hidden = false
  providerBehavior.hidden = true
  renderPresetCategories()
  renderPresetGrid()
  presetScroll.scrollTop = 0
  presetSearch.focus()
}

function closePresetView() {
  presetView.hidden = true
  providerForm.hidden = true
  providerListView.hidden = false
  providerBehavior.hidden = false
  state.preset = null
}

function confirmProviderDiscard() {
  if (!state.providerDirty) return true
  return window.confirm('有未保存的修改，放弃吗？')
}

function resetProviderView() {
  providerForm.hidden = true
  presetView.hidden = true
  providerListView.hidden = false
  providerBehavior.hidden = false
  state.editingProvider = null
  state.preset = null
  state.providerDirty = false
}

/* ---------- 添加 / 编辑表单 ---------- */
function openProviderForm(id, preset = null) {
  const provider = id ? providerById(id) : null
  const source = provider || preset
  const models = provider ? (provider.models || []) : (preset?.models || [])
  const kind = provider?.kind || preset?.kind || 'openai'

  state.editingProvider = id || null
  state.preset = preset
  state.fetchedModels = []
  state.selectedModels = [...models]
  state.providerDirty = false

  providerFormTitle.textContent = provider ? '编辑提供商' : '添加提供商'
  pfName.value = source?.name || ''
  pfCategory.value = provider?.category || presetCategoryFor(preset) || 'custom'
  pfNotes.value = provider?.notes || ''
  pfWebsite.value = provider?.website || preset?.website || ''
  const endpointList = provider
    ? (provider.endpoints?.length ? provider.endpoints : [provider.base_url])
    : [preset?.base_url]
  pfEndpoints.value = endpointList.filter(Boolean).join('\n')
  state.formIcon = provider?.icon || preset?.icon_file || ''
  state.formIconColor = provider?.icon_color || preset?.color || '#9ca3af'
  pfFailover.checked = !!provider?.in_failover_queue
  syncIconPreview()
  pfSpeedResult.textContent = ''
  pfSpeedResult.className = 'endpoint-result'
  pfSpeedList.hidden = true
  pfSpeedList.innerHTML = ''
  pfKind.value = kind
  pfAuth.value = source?.auth || 'token'
  pfAuthRow.hidden = kind !== 'anthropic'
  pfBaseUrl.value = source?.base_url || ''
  pfModels.value = models.join(', ')
  pfPriceIn.value = provider?.pricing?.input || preset?.pricing?.input || ''
  pfPriceOut.value = provider?.pricing?.output || preset?.pricing?.output || ''
  pfPriceCached.value = provider?.pricing?.cached_input || preset?.pricing?.cached_input || ''
  pfCurrency.value = (provider?.pricing?.currency || preset?.pricing?.currency || 'CNY').toUpperCase() === 'USD' ? 'USD' : 'CNY'
  pfContextWindow.value = provider?.context_window || ''
  pfMaxTokens.value = provider?.max_tokens || ''
  pfKey.value = ''
  pfKey.placeholder = provider?.has_key
    ? `已保存（…${provider.key_hint || '环境变量'}），留空不改`
    : 'sk-…'
  const keyUrl = preset?.api_key_url || (provider ? presetFor(provider)?.api_key_url : '')
  pfKeyLink.hidden = !keyUrl
  pfKeyLink.href = keyUrl || '#'

  pfDelete.hidden = !provider
  pfDelete.disabled = !!provider?.active
  pfDelete.title = provider?.active
    ? '当前正在使用这个提供商，先切换到别家再删'
    : ''
  presetBar.hidden = !preset
  presetChip.textContent = preset ? `${preset.name} · ${preset.domain || preset.desc}` : ''
  modelPicker.hidden = true
  modelFilter.value = ''
  modelList.innerHTML = ''

  providerListView.hidden = true
  presetView.hidden = true
  providerBehavior.hidden = true
  providerForm.hidden = false
  providerForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function closeProviderForm(force = false) {
  if (providerForm.hidden) return true
  if (!force && !confirmProviderDiscard()) return false
  state.editingProvider = null
  state.preset = null
  state.providerDirty = false
  providerForm.hidden = true
  presetView.hidden = true
  providerListView.hidden = false
  providerBehavior.hidden = false
  return true
}

async function saveProviderForm() {
  const payload = {
    name: pfName.value.trim(),
    base_url: pfBaseUrl.value.trim(),
    endpoints: pfEndpoints.value.split(/\r?\n+/).map((line) => line.trim()).filter(Boolean),
    models: pfModels.value,
    kind: pfKind.value,
    auth: pfAuth.value,
    category: pfCategory.value,
    notes: pfNotes.value.trim(),
    website: pfWebsite.value.trim(),
    icon: state.formIcon,
    icon_color: state.formIconColor,
    in_failover_queue: pfFailover.checked,
    api_key_url: state.preset?.api_key_url || providerById(state.editingProvider)?.api_key_url || '',
    pricing: {
      input: Math.max(0, Number(pfPriceIn.value) || 0),
      output: Math.max(0, Number(pfPriceOut.value) || 0),
      cached_input: Math.max(0, Number(pfPriceCached.value) || 0) || undefined,
      currency: pfCurrency.value || 'CNY',
    },
    context_window: Number(pfContextWindow.value) || '',
    max_tokens: Number(pfMaxTokens.value) || '',
  }
  if (state.editingProvider) payload.id = state.editingProvider
  const apiKey = pfKey.value.trim()
  if (apiKey) payload.api_key = apiKey

  const res = await fetch('/api/provider', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '保存失败')
    return
  }
  closeProviderForm(true)
  await loadProviders()
  await loadSettings()
  if (res.provider?.reloaded === false) {
    toast('已保存，但模型客户端重建失败（检查密钥）')
  } else if (res.provider?.active) {
    toast('提供商已保存')
  } else {
    toast('已保存，点“设为当前”启用')
  }
}

async function deleteProvider() {
  if (!state.editingProvider) return
  const provider = providerById(state.editingProvider)
  if (provider?.active) {
    toast('当前正在使用这个提供商，先切换到别家再删')
    return
  }
  if (!window.confirm('删除这个模型提供商？')) return
  const res = await fetch('/api/provider', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: state.editingProvider }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '删除失败')
    return
  }
  closeProviderForm(true)
  await loadProviders()
  toast('已删除')
}

async function duplicateProvider(id) {
  const res = await fetch('/api/provider/duplicate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '复制失败')
    return
  }
  await loadProviders()
  toast('已复制，点“编辑”改名称和 Key')
}

/* ---------- 表单：图标 / 测试连接 / 端点测速 ---------- */
function syncIconPreview() {
  pfIconPreview.innerHTML = ''
  pfIconPreview.style.background = state.formIconColor || '#9ca3af'
  if (state.formIcon) {
    const image = document.createElement('img')
    image.src = `/static/provider-icons/${state.formIcon}`
    image.alt = ''
    image.onerror = () => {
      image.remove()
      pfIconPreview.textContent = (pfName.value.trim() || '?').charAt(0).toUpperCase()
    }
    pfIconPreview.appendChild(image)
  } else {
    pfIconPreview.textContent = (pfName.value.trim() || '?').charAt(0).toUpperCase()
  }
  if (state.formIconColor) pfIconColor.value = state.formIconColor
}

async function checkProviderForm() {
  const base = pfBaseUrl.value.trim()
  if (!base) {
    toast('先填 Base URL')
    return
  }
  pfCheck.disabled = true
  pfCheck.textContent = '测试中…'
  try {
    const res = await fetch('/api/provider/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: base }),
    }).then((r) => r.json())
    if (!res.ok) {
      pfSpeedResult.textContent = res.error || '测试失败'
      pfSpeedResult.className = 'endpoint-result failed'
      return
    }
    if (!res.reachable) {
      pfSpeedResult.textContent = `不可达（${res.error || '网络错误'}）`
      pfSpeedResult.className = 'endpoint-result failed'
      pfSpeedResult.title = ''
    } else if (res.level === 'degraded') {
      pfSpeedResult.textContent = `可达但较慢 · ${res.latency_ms}ms`
      pfSpeedResult.className = 'endpoint-result warn'
      pfSpeedResult.title = `HTTP ${res.status}`
    } else {
      pfSpeedResult.textContent = `可达 · ${res.latency_ms}ms`
      pfSpeedResult.className = 'endpoint-result ok'
      pfSpeedResult.title = `HTTP ${res.status}（只测可达，不验证 Key / 模型）`
    }
  } finally {
    pfCheck.disabled = false
    pfCheck.textContent = '测试连接'
  }
}

async function speedTestForm() {
  let urls = pfEndpoints.value.split(/\r?\n+/).map((line) => line.trim()).filter(Boolean)
  const base = pfBaseUrl.value.trim()
  if (base && !urls.includes(base)) urls.unshift(base)
  if (!urls.length) {
    toast('先填端点（至少一个）')
    return
  }
  pfSpeedTest.disabled = true
  pfSpeedTest.textContent = '测速中…'
  pfSpeedResult.textContent = ''
  try {
    const res = await fetch('/api/provider/speedtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls }),
    }).then((r) => r.json())
    if (!res.ok) {
      toast(res.error || '测速失败')
      return
    }
    pfSpeedList.hidden = false
    pfSpeedList.innerHTML = ''
    for (const item of res.results || []) {
      const row = document.createElement('div')
      row.className = 'speed-item' + (item.url === res.best ? ' best' : '')
        + (item.ok ? '' : ' failed')
      const url = document.createElement('span')
      url.textContent = item.url + (item.url === res.best ? ' · 最快' : '')
      const lat = document.createElement('span')
      lat.className = 'lat'
      lat.textContent = item.ok ? `${item.latency_ms}ms` : '不可达'
      row.append(url, lat)
      pfSpeedList.appendChild(row)
    }
    if (res.best && res.best !== pfBaseUrl.value.trim()) {
      pfBaseUrl.value = res.best
      pfEndpoints.value = [res.best, ...urls.filter((url) => url !== res.best)].join('\n')
      state.providerDirty = true
      toast('已自动选最快的端点')
    }
  } finally {
    pfSpeedTest.disabled = false
    pfSpeedTest.textContent = '测速'
  }
}

/* ---------- 图标选择 ---------- */
function iconCatalog() {
  const seen = new Map()
  for (const preset of PROVIDER_PRESETS) {
    if (preset.icon_file && !seen.has(preset.icon_file)) {
      seen.set(preset.icon_file, {
        file: preset.icon_file,
        name: preset.name,
        color: preset.color || '#9ca3af',
      })
    }
  }
  return [...seen.values()]
}

function renderIconGrid() {
  const query = iconSearch.value.trim().toLowerCase()
  iconGrid.innerHTML = ''
  for (const entry of iconCatalog()) {
    if (query && !`${entry.name} ${entry.file}`.toLowerCase().includes(query)) continue
    const cell = document.createElement('button')
    cell.type = 'button'
    cell.className = 'icon-cell' + (entry.file === state.formIcon ? ' on' : '')
    const image = document.createElement('img')
    image.src = `/static/provider-icons/${entry.file}`
    image.alt = ''
    const label = document.createElement('span')
    label.textContent = entry.name
    cell.append(image, label)
    cell.addEventListener('click', () => {
      state.formIcon = entry.file
      state.formIconColor = entry.color
      state.providerDirty = true
      syncIconPreview()
      iconMask.hidden = true
    })
    iconGrid.appendChild(cell)
  }
}

function openIconPicker() {
  iconSearch.value = ''
  iconMask.hidden = false
  renderIconGrid()
}

/* ---------- 导入 / 导出 ---------- */
async function openProviderExport() {
  state.ioMode = 'export'
  providerIoTitle.textContent = '导出供应商'
  providerIoHint.textContent = '内容里包含 API Key 明文，只复制给你自己；导入时按 id 覆盖、新 id 追加，不会自动切换当前供应商。'
  providerIoText.value = '导出中…'
  providerIoOk.hidden = true
  providerIoCopy.hidden = false
  providerIoMask.hidden = false
  const res = await fetch('/api/providers/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  }).then((r) => r.json())
  if (!res.ok) {
    providerIoText.value = res.error || '导出失败'
    return
  }
  providerIoText.value = JSON.stringify(res, null, 2)
}

function openProviderImport() {
  state.ioMode = 'import'
  providerIoTitle.textContent = '导入供应商'
  providerIoHint.textContent = '粘贴 Spirit 导出的 JSON（{"providers": [...]}）。同 id 覆盖、新 id 追加；不会自动切换当前供应商。'
  providerIoText.value = ''
  providerIoOk.hidden = false
  providerIoCopy.hidden = true
  providerIoMask.hidden = false
  providerIoText.focus()
}

async function providerIoSubmit() {
  if (state.ioMode !== 'import') return
  let payload
  try {
    payload = JSON.parse(providerIoText.value)
  } catch {
    toast('JSON 解析失败，检查是不是完整复制')
    return
  }
  const res = await fetch('/api/providers/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Array.isArray(payload) ? { providers: payload } : payload),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '导入失败')
    return
  }
  providerIoMask.hidden = true
  await loadProviders()
  const note = [
    res.errors?.length ? `${res.errors.length} 条跳过` : '',
    res.warnings?.length ? `${res.warnings.length} 条警告` : '',
  ].filter(Boolean).join('，')
  toast(`已导入 ${res.imported} 个供应商${note ? `（${note}）` : ''}`)
  if (res.warnings?.length) {
    setTimeout(() => toast(res.warnings[0]), 1600)
  }
}

async function fetchProviderModels() {
  const baseUrl = pfBaseUrl.value.trim()
  if (!baseUrl) {
    toast('先填 Base URL')
    return
  }
  pfFetchModels.disabled = true
  pfFetchModels.textContent = '获取中…'
  try {
    const res = await fetch('/api/provider/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        base_url: baseUrl,
        api_key: pfKey.value.trim(),
        id: state.editingProvider || '',
        kind: pfKind.value,
        auth: pfAuth.value,
      }),
    }).then((r) => r.json())
    if (!res.ok) {
      toast(res.error || '获取模型失败')
      return
    }
    state.fetchedModels = res.models || []
    modelPicker.hidden = false
    modelFilter.value = ''
    renderModelPicker()
    if (!state.fetchedModels.length) toast('端点没有返回模型')
  } catch {
    toast('获取模型失败')
  } finally {
    pfFetchModels.disabled = false
    pfFetchModels.textContent = '获取模型'
  }
}

function renderModelPicker() {
  const query = modelFilter.value.trim().toLowerCase()
  const filtered = state.fetchedModels.filter(
    (model) => !query || model.toLowerCase().includes(query),
  )
  const shown = filtered.slice(0, 400)
  modelList.innerHTML = ''

  if (!state.fetchedModels.length) {
    const empty = document.createElement('div')
    empty.className = 'model-empty'
    empty.textContent = '先点“获取模型”，或者直接在上面手填。'
    modelList.appendChild(empty)
    return
  }
  if (!shown.length) {
    const empty = document.createElement('div')
    empty.className = 'model-empty'
    empty.textContent = '没有匹配的模型。'
    modelList.appendChild(empty)
    return
  }

  for (const model of shown) {
    const selected = state.selectedModels.includes(model)
    const row = document.createElement('button')
    row.type = 'button'
    row.className = 'model-option' + (selected ? ' on' : '')
    row.innerHTML = `<span>${escapeHtml(model)}</span><span class="check">${selected ? '✓' : ''}</span>`
    row.addEventListener('click', () => toggleModel(model))
    modelList.appendChild(row)
  }
  if (filtered.length > shown.length) {
    const more = document.createElement('div')
    more.className = 'model-empty'
    more.textContent = `还有 ${filtered.length - shown.length} 个，输入筛选。`
    modelList.appendChild(more)
  }
}

function toggleModel(model) {
  const index = state.selectedModels.indexOf(model)
  if (index >= 0) {
    state.selectedModels.splice(index, 1)
  } else {
    state.selectedModels.push(model)
  }
  pfModels.value = state.selectedModels.join(', ')
  state.providerDirty = true
  renderModelPicker()
}

function syncModelSelectionFromInput() {
  state.selectedModels = pfModels.value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  if (!modelPicker.hidden) renderModelPicker()
}

async function activateProvider(id, model = null) {
  const next = providerById(id)
  const current = providerById(state.providerId)
  if (state.running && next && current && next.kind !== current.kind) {
    const ok = window.confirm(
      `当前轮还在跑，跨协议（${providerKindLabel(current.kind)} → ${providerKindLabel(next.kind)}）中途切换可能让上下文不兼容。继续？`,
    )
    if (!ok) return
  }
  const wasRunning = state.running
  const res = await fetch('/api/provider/active', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, model }),
  }).then((r) => r.json())
  if (res.error) {
    toast(res.error)
    return
  }
  await loadProviders()
  await loadSettings()
  const name = providerById(id)?.name || id
  const suffix = wasRunning ? '（下一次模型请求生效）' : ''
  toast(res.ok
    ? `已切换到 ${name}${suffix}`
    : `已切换 ${name}，但客户端重建失败（检查密钥）`)
  popModelList.hidden = true
}

async function selectModel(model) {
  await activateProvider(state.providerId, model)
}

function askInput(title, value = '') {
  return new Promise((resolve) => {
    const mask = document.getElementById('promptMask')
    const input = document.getElementById('promptInput')
    const ok = document.getElementById('promptOk')
    const cancel = document.getElementById('promptCancel')
    document.getElementById('promptTitle').textContent = title
    input.value = value

    const cleanup = () => {
      mask.hidden = true
      ok.removeEventListener('click', onOk)
      cancel.removeEventListener('click', onCancel)
      input.removeEventListener('keydown', onKey)
      mask.removeEventListener('click', onMask)
    }
    const done = (result) => {
      cleanup()
      resolve(result)
    }
    const onOk = () => done(input.value.trim() || null)
    const onCancel = () => done(null)
    const onKey = (event) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        event.stopPropagation()
        onOk()
      } else if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onCancel()
      }
    }
    const onMask = (event) => {
      if (event.target === mask) onCancel()
    }

    ok.addEventListener('click', onOk)
    cancel.addEventListener('click', onCancel)
    input.addEventListener('keydown', onKey)
    mask.addEventListener('click', onMask)
    mask.hidden = false
    input.focus()
    input.select()
  })
}

/* ---------- 渗透授权范围（入口在场景浮层里） ---------- */
function updateScopeUI() {
  renderScenarioPop()
}

async function loadScope() {
  try {
    const data = await fetch('/api/scope').then((res) => res.json())
    if (data.ok) state.scope = data.scope || []
  } catch { /* 忽略 */ }
  updateScopeUI()
}

function openScopeDialog() {
  scopeInput.value = state.scope.join('\n')
  scopeMask.hidden = false
  scopeInput.focus()
}

function closeScopeDialog() {
  scopeMask.hidden = true
}

async function saveScope() {
  const scope = scopeInput.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  try {
    const res = await fetch('/api/scope', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope }),
    }).then((r) => r.json())
    if (!res.ok) {
      toast(res.error || '保存失败')
      return
    }
    state.scope = res.scope || []
    updateScopeUI()
    closeScopeDialog()
    toast(state.scope.length ? `授权范围：${state.scope.length} 个目标` : '授权范围已清空')
  } catch {
    toast('保存失败')
  }
}

function applySettings(data) {
  state.thinking = !!data.thinking
  state.effort = normalizeEffort(data.effort || state.effort)
  state.model = data.model || state.model
  state.workdir = data.workdir || state.workdir
  state.approval = data.approval ? normalizeApproval(data.approval) : state.approval
  state.access = ACCESS_LABEL[data.access] ? data.access : state.access
  state.untrusted = ['warn', 'confirm', 'block'].includes(data.untrusted_policy)
    ? data.untrusted_policy
    : state.untrusted
  state.scenario = data.scenario || state.scenario
  applyScenarioTheme()
  state.sessionDir = data.session_dir || state.sessionDir
  state.providerId = data.provider_id || state.providerId
  syncModelUI()
}

/* ---------- 确认方式 / 打开路径 ---------- */
async function setApproval(mode) {
  const res = await fetch('/api/approval-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '切换失败')
    return
  }
  state.approval = normalizeApproval(res.approval || mode)
  syncModelUI()
  toast(`操作模式：${APPROVAL_LABEL[state.approval]}`)
}

async function setAccess(access) {
  const res = await fetch('/api/access-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ access }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '切换失败')
    return
  }
  state.access = res.access || access
  syncModelUI()
  toast(`工作范围：${ACCESS_LABEL[state.access] || state.access}`)
}

async function openTarget(target, label) {
  const res = await fetch('/api/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '打开失败')
    return
  }
  toast(`已打开${label}`)
}

/* ---------- 场景 ---------- */
function applyScenarioTheme() {
  document.body.dataset.scenario = state.scenario || 'daily'
}

async function loadScenarios() {
  try {
    const data = await fetch(sessionUrl('/api/scenarios')).then((res) => res.json())
    if (!data.ok) return
    state.scenarios = data.scenarios || []
    state.scenario = data.current || state.scenario
    state.scenarioLocked = !!data.locked
    applyScenarioTheme()
    renderScenarioPop()
    syncModelUI()
    const pentest = state.scenario === 'pentest'
    if (!pentest) {
      if (infoButton) infoButton.hidden = true
      if (assetsButton) assetsButton.hidden = true
      document.getElementById('tabMore')?.classList.remove('active')
    }
  } catch { /* 引擎未起 */ }
}

function renderScenarioPop() {
  scenarioPop.innerHTML = ''
  for (const item of state.scenarios) {
    const active = item.id === state.scenario
    const lockedOut = state.scenarioLocked && !active
    const button = document.createElement('button')
    button.className = 'scenario-option' + (active ? ' active' : '')
      + (lockedOut ? ' disabled' : '')
    const name = document.createElement('span')
    name.className = 'name'
    name.textContent = item.name
    const desc = document.createElement('span')
    desc.className = 'desc'
    desc.textContent = item.description || ''
    button.appendChild(name)
    button.appendChild(desc)
    button.addEventListener('click', (event) => {
      event.stopPropagation()
      if (lockedOut) {
        toast('会话已经开始，场景不能再切换；新建会话时再选')
        return
      }
      selectScenario(item.id)
    })
    scenarioPop.appendChild(button)
  }

  if (state.scenario === 'pentest') {
    const sep = document.createElement('div')
    sep.className = 'menu-sep'
    scenarioPop.appendChild(sep)
    const scope = document.createElement('button')
    scope.className = 'scenario-scope' + (state.scope.length ? '' : ' warn')
    scope.innerHTML = '<span>授权范围</span>'
      + `<span class="scope-count">${state.scope.length ? `${state.scope.length} 个目标` : '未设置'}</span>`
    scope.addEventListener('click', (event) => {
      event.stopPropagation()
      scenarioPop.hidden = true
      openScopeDialog()
    })
    scenarioPop.appendChild(scope)
  }

  const hint = document.createElement('div')
  hint.className = 'menu-hint'
  hint.textContent = state.scenarioLocked
    ? '会话已经开始，场景已锁定；新建会话可以重新选'
    : '开局前选好；发出第一条消息后锁定'
  scenarioPop.appendChild(hint)
}

async function selectScenario(id) {
  scenarioPop.hidden = true
  if (state.scenarioLocked && id !== state.scenario) {
    toast('会话已经开始，场景不能再切换；新建会话时再选')
    return
  }
  const res = await fetch('/api/scenario', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, session: state.sessionId }),
  }).then((r) => r.json())
  if (!res.ok) {
    toast(res.error || '切换失败')
    return
  }
  state.scenario = res.current || id
  applyScenarioTheme()
  if (res.settings) applySettings(res.settings)
  await loadScenarios()
  const name = state.scenarios.find((item) => item.id === state.scenario)?.name
  toast(`场景：${name || state.scenario}（发出第一条消息后锁定）`)
}

function positionScenarioPop() {
  const rect = scenarioChip.getBoundingClientRect()
  scenarioPop.style.left = `${Math.max(12, rect.left)}px`
  scenarioPop.style.top = `${rect.bottom + 6}px`
}

function positionApprovalPop() {
  const rect = workdirChip.getBoundingClientRect()
  approvalPop.style.left = `${Math.max(12, rect.left)}px`
  approvalPop.style.bottom = `${Math.max(12, window.innerHeight - rect.top + 8)}px`
}

function positionAccessPop() {
  const rect = accessChip.getBoundingClientRect()
  accessPop.style.left = `${Math.max(12, rect.left)}px`
  accessPop.style.bottom = `${Math.max(12, window.innerHeight - rect.top + 8)}px`
}

function selectSettingsPanel(panel) {
  for (const item of document.querySelectorAll('.settings-nav-item')) {
    item.classList.toggle('active', item.dataset.panel === panel)
  }
  for (const section of document.querySelectorAll('.settings-panel')) {
    section.hidden = section.dataset.panel !== panel
  }
  if (panel === 'disk') loadDisk()
  if (panel === 'general') loadBrowserStatus()
}

const DISK_LABELS = {
  workspace: '工作区（子体系）',
  artifacts: '能力产物',
  sessions: '会话',
  logs: '日志',
  sandbox: '沙箱',
  uploads: '上传',
  projects: '项目资产',
}

const DISK_CLEAN = {
  workspace: {
    label: '清理临时',
    confirm: '只删除工作区 tmp/ 里的临时文件，脚本 / 文档 / 图片等保留。继续？',
    done: '已清理临时文件',
  },
  artifacts: {
    label: '清理',
    confirm: '清理能力产物？工具落盘的大结果会删除，会话和工作区不受影响。',
    done: '已清理能力产物',
  },
  sessions: {
    label: '清理空会话',
    confirm: '只删除没有任何记录的空白会话，当前会话和有内容的会话保留。继续？',
    done: '已清理空会话',
  },
  logs: {
    label: '清空',
    confirm: '清空日志内容（不删除文件）？正在写的日志也可能被清空。',
    done: '已清空日志',
  },
  sandbox: {
    label: '清理',
    confirm: '清理沙箱临时目录？正在运行的沙箱可能失败。',
    done: '已清理沙箱',
  },
  projects: {
    label: '清理',
    confirm: '清理所有项目的资产库和原始响应？会话与工作区不受影响。',
    done: '已清理项目资产',
  },
  uploads: {
    label: '清理未引用',
    confirm: '清理没有被任何会话引用的上传图片？会话历史里用到的图片会保留。',
    done: '已清理未引用图片',
  },
}

function formatBytes(size) {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`
}

async function loadDisk() {
  if (!diskAreaList) return
  const res = await fetch('/api/disk').then((r) => r.json())
  if (!res.ok) return
  diskAreaList.innerHTML = ''
  for (const [name, area] of Object.entries(res.areas || {})) {
    const row = document.createElement('div')
    row.className = 'path-row'
    row.dataset.area = name
    const text = document.createElement('span')
    text.className = 'path-text'
    text.textContent = `${DISK_LABELS[name] || name} · ${formatBytes(area.bytes)}${area.truncated ? '+' : ''} · ${area.files} 个文件`
    text.title = area.path
    const open = document.createElement('button')
    open.className = 'ghost-btn mini'
    open.textContent = '打开'
    open.addEventListener('click', () => openTarget(name, DISK_LABELS[name] || name))
    row.append(text, open)
    const cleanSpec = DISK_CLEAN[name]
    if (cleanSpec) {
      const clean = document.createElement('button')
      clean.className = 'ghost-btn mini'
      clean.textContent = cleanSpec.label
      clean.addEventListener('click', async () => {
        if (!window.confirm(cleanSpec.confirm)) return
        const result = await fetch('/api/disk/clear', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ area: name }),
        }).then((r) => r.json())
        if (!result.ok) {
          toast(result.error || '清理失败')
          return
        }
        toast(`${cleanSpec.done}（${result.removed} 项）`)
        loadDisk()
      })
      row.append(clean)
    }
    diskAreaList.appendChild(row)
  }
}

/* ---------- 右侧信息收集抽屉 ---------- */
let drawerPoll = 0
let drawerTab = 'collect'
let drawerProjectSession = 'primary'
let drawerProjects = []

function drawerSession() {
  return drawerProjectSession || state.sessionId || 'primary'
}

function openDrawer(tab = drawerTab) {
  drawerTab = tab
  drawerProjectSession = state.sessionId || 'primary'
  infoDrawer.hidden = false
  drawerMask.hidden = false
  requestAnimationFrame(() => {
    infoDrawer.classList.add('open')
    drawerMask.classList.add('open')
  })
  drawerProject.textContent = `当前项目：${convTitle.textContent || drawerProjectSession}`
  setDrawerTab(tab)
  loadAssetPlatforms()
  loadCollectTools()
  loadProjects()
  loadAssets()
  loadProjectCsvs()
  clearInterval(drawerPoll)
  drawerPoll = setInterval(() => {
    if (drawerMask.hidden) return
    if (drawerTab === 'assets' || drawerTab === 'queries') loadAssets()
  }, 3000)
}

function closeDrawer() {
  infoDrawer.classList.remove('open')
  drawerMask.classList.remove('open')
  clearInterval(drawerPoll)
  drawerPoll = 0
  setTimeout(() => {
    if (!infoDrawer.classList.contains('open')) {
      infoDrawer.hidden = true
      drawerMask.hidden = true
    }
  }, 180)
}

async function loadProjects() {
  try {
    const data = await fetch(sessionUrl('/api/assets/projects')).then((res) => res.json())
    if (!data.ok) return
    drawerProjects = data.projects || []
    try {
      const sessions = await fetch('/api/sessions').then((res) => res.json())
      const titles = {}
      for (const row of sessions || []) {
        const key = row.session || ''
        if (key && row.title) titles[key] = row.title
      }
      for (const item of drawerProjects) {
        if (titles[item.session]) item.title = titles[item.session]
      }
    } catch { /* 标题取不到就用 session id */ }
    const tabs = document.getElementById('projectTabs')
    tabs.innerHTML = ''
    let hasCurrent = false
    for (const item of drawerProjects) {
      if (item.session === drawerProjectSession) hasCurrent = true
      const button = document.createElement('button')
      button.className = 'project-tab' + (item.session === drawerProjectSession ? ' active' : '')
      button.textContent = item.title || item.session
      button.title = `${item.title || item.session} · ${item.total || 0} 条`
      button.addEventListener('click', () => {
        drawerProjectSession = item.session
        drawerProject.textContent = `当前项目：${item.title || item.session}`
        for (const other of tabs.querySelectorAll('.project-tab')) {
          other.classList.toggle('active', other === button)
        }
        loadAssets()
        loadProjectCsvs()
      })
      tabs.appendChild(button)
    }
    if (!hasCurrent) {
      // 当前项目还没产生资产目录：也给它一个页签，空状态可见
      const button = document.createElement('button')
      button.className = 'project-tab active'
      button.textContent = convTitle.textContent || drawerProjectSession
      button.addEventListener('click', () => {
        drawerProjectSession = state.sessionId || 'primary'
        loadAssets()
      })
      tabs.prepend(button)
    }
  } catch { /* 引擎未起 */ }
}

function setDrawerTab(tab) {
  drawerTab = tab
  for (const button of document.querySelectorAll('.drawer-tabs button')) {
    button.classList.toggle('active', button.dataset.dtab === tab)
  }
  for (const panel of document.querySelectorAll('.drawer-panel')) {
    panel.hidden = panel.dataset.dpanel !== tab
  }
  if (tab === 'assets' || tab === 'queries') loadAssets()
  if (tab === 'collect') loadProjectCsvs()
}

function platformStatusText(state) {
  const status = state.status || {}
  if (!state.enabled) return '未启用'
  if (!state.configured) return '未配置 Key'
  if (status.at && status.ok === false) return '验证失败'
  if (status.at && status.ok) return `已连接${status.quota ? ' · ' + status.quota : ''}`
  return '待验证'
}

async function savePlatformEnabled(item, checked, input) {
  try {
    const result = await fetch('/api/assets/platforms', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ platform: item.id, enabled: checked }),
    }).then((res) => res.json())
    if (!result.ok) {
      input.checked = !checked
      toast(result.error || '保存失败')
      return
    }
    loadAssetPlatforms()
  } catch {
    input.checked = !checked
    toast('保存失败')
  }
}

function renderPlatforms(items) {
  assetPlatformList.innerHTML = ''
  for (const item of items) {
    const card = document.createElement('div')
    card.className = 'platform-card'
    const head = document.createElement('div')
    head.className = 'platform-head'
    const name = document.createElement('span')
    name.className = 'platform-name'
    name.textContent = item.label
    const label = document.createElement('label')
    label.className = 'switch-line'
    const enabled = document.createElement('input')
    enabled.type = 'checkbox'
    enabled.checked = !!item.enabled
    enabled.addEventListener('change', () => savePlatformEnabled(item, enabled.checked, enabled))
    label.append(enabled, document.createTextNode('启用'))
    const status = document.createElement('span')
    status.className = 'platform-state'
    const text = platformStatusText(item)
    status.textContent = text
    if (text.startsWith('已连接')) status.classList.add('ok')
    if (text === '验证失败') status.classList.add('bad')
    const toggle = document.createElement('button')
    toggle.className = 'ghost-btn mini platform-toggle'
    toggle.textContent = '配置'
    head.append(name, label, status, toggle)
    card.appendChild(head)

    const body = document.createElement('div')
    body.className = 'platform-body'
    const fields = document.createElement('div')
    fields.className = 'platform-fields'
    const key = document.createElement('input')
    key.className = 'setting-input'
    key.type = 'password'
    key.autocomplete = 'off'
    key.placeholder = item.configured ? 'API Key 已配置（留空保持不变）' : 'API Key'
    const base = document.createElement('input')
    base.className = 'setting-input'
    base.placeholder = 'BaseURL（可选，反代 / 镜像）'
    base.value = item.base_url || ''
    fields.append(key, base)
    body.appendChild(fields)

    const syntax = document.createElement('div')
    syntax.className = 'platform-syntax'
    syntax.textContent = item.syntax
    body.appendChild(syntax)

    const actions = document.createElement('div')
    actions.className = 'platform-actions'
    const save = document.createElement('button')
    save.className = 'ghost-btn mini'
    save.textContent = '保存'
    save.addEventListener('click', async () => {
      const payload = { platform: item.id, enabled: enabled.checked, base_url: base.value }
      if (key.value.trim()) payload.key = key.value.trim()
      const result = await fetch('/api/assets/platforms', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then((res) => res.json())
      if (!result.ok) toast(result.error || '保存失败')
      else {
        key.value = ''
        toast(`${item.label} 已保存`)
        loadAssetPlatforms()
      }
    })
    const test = document.createElement('button')
    test.className = 'ghost-btn mini'
    test.textContent = '测试'
    test.addEventListener('click', async () => {
      const result = await fetch('/api/assets/platform/test', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: item.id }),
      }).then((res) => res.json())
      if (!result.ok) toast(result.error || '测试失败')
      else if (result.status?.ok) toast(`${item.label} 连接正常`)
      else toast(`${item.label} 验证失败：${result.status?.error || 'Key 无效'}`)
      loadAssetPlatforms()
    })
    actions.append(save, test)
    body.appendChild(actions)
    body.hidden = !(item.enabled && !item.configured)
    toggle.textContent = body.hidden ? '配置' : '收起'
    toggle.addEventListener('click', () => {
      body.hidden = !body.hidden
      toggle.textContent = body.hidden ? '配置' : '收起'
      card.classList.toggle('open', !body.hidden)
    })
    card.classList.toggle('open', !body.hidden)
    card.appendChild(body)
    assetPlatformList.appendChild(card)
  }
}

async function loadCollectTools() {
  if (!collectTools) return
  try {
    const data = await fetch('/api/assets/collect-tools').then((res) => res.json())
    if (!data.ok) return
    collectTools.innerHTML = ''
    for (const tool of data.tools || []) {
      const row = document.createElement('div')
      row.className = 'collect-tool'
      const dot = document.createElement('span')
      dot.className = 'dot' + (tool.ok ? '' : ' bad')
      const name = document.createElement('span')
      name.className = 'name'
      name.textContent = tool.name
      const detail = document.createElement('span')
      detail.className = 'detail'
      detail.textContent = tool.detail
      row.append(dot, name, detail)
      collectTools.appendChild(row)
    }
  } catch { /* 引擎未起 */ }
}

let csvLoadSeq = 0
async function loadProjectCsvs() {
  if (!projectCsvList) return
  const seq = ++csvLoadSeq
  try {
    const data = await fetch(`/api/assets/csvs?session=${encodeURIComponent(drawerSession())}`)
      .then((res) => res.json())
    if (seq !== csvLoadSeq || !data.ok) return
    projectCsvList.innerHTML = ''
    const files = data.files || []
    if (!files.length) {
      const empty = document.createElement('div')
      empty.className = 'drawer-empty'
      empty.textContent = '还没有总表。跑一次信息收集后会生成 assets.csv。'
      projectCsvList.appendChild(empty)
      return
    }
    for (const file of files) {
      const row = document.createElement('button')
      row.className = 'csv-file'
      if (file.main) row.classList.add('csv-main')
      const name = document.createElement('span')
      name.className = 'csv-file-name'
      name.textContent = file.main ? `${file.name}（项目总表）` : file.name
      const meta = document.createElement('span')
      meta.className = 'csv-file-meta'
      meta.textContent = `${file.rows} 行 · ${formatBytes(file.bytes)} · 打开`
      row.append(name, meta)
      row.addEventListener('click', () => openProjectCsv(file.name))
      projectCsvList.appendChild(row)
    }
  } catch { /* 引擎未起 */ }
}

async function openProjectCsv(name) {
  try {
    const data = await fetch('/api/assets/csv/open', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: drawerSession(), name }),
    }).then((res) => res.json())
    if (!data.ok) toast(data.error || '打开失败')
  } catch { toast('打开失败') }
}

async function loadAssetPlatforms() {
  try {
    const data = await fetch('/api/assets/platforms').then((res) => res.json())
    if (data.ok) renderPlatforms(data.platforms || [])
  } catch { /* 引擎未起 */ }
}

async function loadAssets() {
  const query = new URLSearchParams()
  query.set('limit', '500')
  if (assetSearch?.value.trim()) query.set('search', assetSearch.value.trim())
  if (assetKind?.value) query.set('kind', assetKind.value)
  query.set('session', drawerSession())
  const url = '/api/assets?' + query.toString()
  try {
    const data = await fetch(url).then((res) => res.json())
    if (!data.ok) return
    renderAssets(data)
  } catch { /* 引擎未起 */ }
}

function renderAssets(data) {
  const summary = data.summary || {}
  assetSummary.innerHTML = ''
  const kindLabels = { domain: '域名', ip: 'IP', url: 'URL', host: '主机' }
  for (const [key, value] of Object.entries(summary.kinds || {})) {
    if (!value) continue
    const chip = document.createElement('span')
    chip.className = 'asset-chip'
    chip.textContent = `${kindLabels[key] || key} ${value}`
    assetSummary.appendChild(chip)
  }
  const total = document.createElement('span')
  total.className = 'asset-chip'
  total.textContent = `共 ${summary.total || 0} 条`
  assetSummary.appendChild(total)

  assetList.innerHTML = ''
  const assets = data.assets || []
  if (!assets.length) {
    const empty = document.createElement('div')
    empty.className = 'drawer-empty'
    empty.textContent = '还没有收集记录。在对话里让 Spirit 查 FOFA / Quake / Hunter，结果会自动进这里。'
    assetList.appendChild(empty)
  } else {
    const table = document.createElement('table')
    table.className = 'asset-table'
    const head = document.createElement('thead')
    head.innerHTML = '<tr><th>类型</th><th>域名 / 地址</th><th>端口</th><th>标题 / 服务</th><th>来源</th></tr>'
    const body = document.createElement('tbody')
    const kindLabels = { domain: '域名', ip: 'IP', url: 'URL', host: '主机' }
    for (const item of assets) {
      const row = document.createElement('tr')
      const kind = document.createElement('td')
      kind.textContent = kindLabels[item.kind] || item.kind || ''
      const value = document.createElement('td')
      value.textContent = item.domain || item.host || item.url || item.ip || ''
      if (item.ip && item.domain && item.ip !== item.domain) value.textContent = `${item.domain} (${item.ip})`
      const port = document.createElement('td')
      port.textContent = item.port || ''
      const title = document.createElement('td')
      title.textContent = [item.title, item.server].filter(Boolean).join(' · ')
      const source = document.createElement('td')
      source.textContent = (item.sources || []).join(', ')
      row.append(kind, value, port, title, source)
      row.title = [item.url, item.protocol, item.os, item.org, item.banner]
        .filter(Boolean).join(' · ')
      body.appendChild(row)
    }
    table.append(head, body)
    assetList.appendChild(table)
  }

  queryList.innerHTML = ''
  const queries = data.queries || []
  if (!queries.length) {
    const empty = document.createElement('div')
    empty.className = 'drawer-empty'
    empty.textContent = '还没有查询记录。'
    queryList.appendChild(empty)
  }
  for (const item of queries) {
    const row = document.createElement('div')
    row.className = 'asset-row'
    const time = new Date((item.at || 0) * 1000).toLocaleTimeString('zh-CN', { hour12: false })
    row.textContent = `${time}  ${item.source}  ${item.query}  · ${item.count} 条`
    queryList.appendChild(row)
  }
}

document.getElementById('drawerClose').addEventListener('click', closeDrawer)
drawerMask.addEventListener('click', closeDrawer)
infoDrawer.addEventListener('click', (event) => event.stopPropagation())
for (const button of document.querySelectorAll('.drawer-tabs button')) {
  button.addEventListener('click', () => setDrawerTab(button.dataset.dtab))
}
document.getElementById('csvImport').addEventListener('click', () => document.getElementById('csvImportFile').click())
document.getElementById('csvImportFile').addEventListener('change', async (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  const text = await file.text()
  const result = await fetch('/api/assets/csv/import', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: drawerSession(), name: file.name, text }),
  }).then((res) => res.json())
  if (!result.ok) toast(result.error || '导入失败')
  else { toast(result.hint || `已导入 ${result.name}`); loadProjectCsvs() }
  event.target.value = ''
})
document.getElementById('assetClear').addEventListener('click', async () => {
  if (!window.confirm('清理当前项目的资产库和原始响应？会话与工作区不受影响。')) return
  const result = await fetch('/api/assets/clear', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session: drawerSession() }),
  }).then((res) => res.json())
  if (result.ok) {
    toast(`已清理 ${result.removed} 个文件`)
    loadAssets()
  } else toast(result.error || '清理失败')
})
assetSearch?.addEventListener('input', () => { clearTimeout(assetSearch._timer); assetSearch._timer = setTimeout(loadAssets, 300) })
assetKind?.addEventListener('change', loadAssets)

function openSettings(panel = 'general') {
  settingsMask.hidden = false
  resetProviderView()
  selectSettingsPanel(panel)
  loadProviders()
}
function closeSettings() {
  if (!providerForm.hidden && !closeProviderForm()) return
  settingsMask.hidden = true
}

/* ---------- 浮层 ---------- */
function positionPopover() {
  const rect = modelPill.getBoundingClientRect()
  popover.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`
  popover.style.bottom = `${Math.max(12, window.innerHeight - rect.top + 8)}px`
}

function togglePopover(show) {
  const next = show ?? popover.hidden
  if (next) positionPopover()
  popover.hidden = !next
}

function openMenu() {
  const rect = document.getElementById('menuBtn').getBoundingClientRect()
  menuPop.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`
  menuPop.style.top = `${rect.bottom + 6}px`
  menuPop.hidden = false
}

function closeMenu() {
  menuPop.hidden = true
}

/* ---------- 发送 ---------- */
async function sendOrStop() {
  if (state.running) {
    state.running = false
    state.stopRequested = true
    updateSendButton()
    if (state.turnHead) state.turnHead.textContent = '正在停止…'
    try {
      await fetch('/api/interrupt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session: state.sessionId }),
      })
    } catch { /* 忽略 */ }
    // 兜底：模型如果还没吐任何事件，引擎不会给 assistant_end，这里自己收尾
    const token = state.turnToken
    setTimeout(() => {
      if (state.turnHead && token === state.turnToken) finishTurn(true, token)
    }, 800)
    toast('已请求停止')
    return
  }
  await send()
}

function imageSrc(url) {
  if (!url) return ''
  if (url.startsWith('/api/') && API_TOKEN) {
    return `${url}?token=${encodeURIComponent(API_TOKEN)}`
  }
  return url
}

function renderAttachPreview() {
  attachPreview.innerHTML = ''
  attachPreview.hidden = !state.pendingImages.length
  state.pendingImages.forEach((item, index) => {
    const thumb = document.createElement('div')
    thumb.className = 'attachThumb'
    const img = document.createElement('img')
    img.src = item.src
    img.alt = '待发送图片'
    const remove = document.createElement('button')
    remove.type = 'button'
    remove.textContent = '×'
    remove.title = '移除'
    remove.addEventListener('click', () => {
      state.pendingImages.splice(index, 1)
      renderAttachPreview()
      updateSendButton()
    })
    thumb.append(img, remove)
    attachPreview.appendChild(thumb)
  })
}

function clearPendingImages() {
  state.pendingImages = []
  renderAttachPreview()
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('读取失败'))
    reader.readAsDataURL(file)
  })
}

async function addImageFile(file) {
  if (!file || !file.type.startsWith('image/')) return
  if (state.pendingImages.length >= 4) {
    toast('最多 4 张图片')
    return
  }
  if (file.size > 8 * 1024 * 1024) {
    toast('图片太大（上限 8MB）')
    return
  }
  try {
    const data = await readAsDataUrl(file)
    const res = await fetch('/api/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data, name: file.name }),
    }).then((r) => r.json())
    if (!res.ok) {
      toast(res.error || '上传失败')
      return
    }
    if (state.pendingImages.length >= 4) {
      toast('最多 4 张图片')
      return
    }
    state.pendingImages.push({ id: res.id, src: data })
    renderAttachPreview()
    updateSendButton()
  } catch (error) {
    toast('图片上传失败：' + error)
  }
}

function addImageFiles(files) {
  for (const file of files || []) addImageFile(file)
}

attachBtn.addEventListener('click', () => imageFile.click())
imageFile.addEventListener('change', () => {
  addImageFiles(imageFile.files)
  imageFile.value = ''
})
input.addEventListener('paste', (event) => {
  const items = event.clipboardData?.items || []
  const files = []
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (files.length) {
    event.preventDefault()
    addImageFiles(files)
  }
})
;['dragover', 'drop'].forEach((type) => {
  composerArea.addEventListener(type, (event) => {
    if (type === 'dragover') {
      event.preventDefault()
      return
    }
    const files = event.dataTransfer?.files || []
    if (files.length) {
      event.preventDefault()
      addImageFiles(files)
    }
  })
})

async function send() {
  const text = input.value.trim()
  const images = state.pendingImages.slice()
  if (!text && !images.length) return

  input.value = ''
  resize()
  clearPendingImages()
  addUser(text, images.map((item) => item.src))
  startTurn()
  state.running = true
  updateSendButton()

  if (convTitle.textContent === '新会话') {
    setTitle((text || '图片').slice(0, 24))
  }

  try {
    const res = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        images: images.map((item) => item.id),
        session: state.sessionId,
      }),
    }).then((r) => r.json())
    if (!res || !res.ok) {
      addError(res?.error || '发送失败', '错误')
      finishTurn(true, state.turnToken)
    } else {
      refreshSessions()   // 发出后立刻在侧栏占位（不必等这一轮结束）
      loadScenarios()     // 这会话已经开始，场景随之锁定
    }
  } catch (err) {
    addError('发送失败：' + err, '错误')
    finishTurn(true, state.turnToken)
  }
  scrollToBottom()
}

function resize() {
  input.style.height = 'auto'
  input.style.height = Math.min(input.scrollHeight, 336) + 'px'
  if (!state.running) updateSendButton()
}

/* ---------- 绑定 ---------- */
sendBtn.addEventListener('click', sendOrStop)
input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendOrStop()
  }
  // Claude 式：Shift+Tab 在「询问 / 自动」之间循环
  if (event.key === 'Tab' && event.shiftKey) {
    event.preventDefault()
    setApproval(state.approval === 'auto' ? 'ask' : 'auto')
  }
})
input.addEventListener('input', resize)

document.getElementById('newSession').addEventListener('click', newSession)
document.getElementById('menuBtn').addEventListener('click', (event) => {
  event.stopPropagation()
  openMenu()
})
infoButton?.addEventListener('click', () => {
  infoButton.hidden = true
  assetsButton.hidden = true
  document.getElementById('tabMore')?.classList.remove('active')
  openDrawer('collect')
})
assetsButton?.addEventListener('click', () => {
  infoButton.hidden = true
  assetsButton.hidden = true
  document.getElementById('tabMore')?.classList.remove('active')
  openDrawer('assets')
})
document.getElementById('panelBtn').addEventListener('click', () => {
  shell.classList.toggle('collapsed')
})
document.getElementById('tabChat').addEventListener('click', showChat)
document.getElementById('tabTrail').addEventListener('click', showTrajectory)
document.getElementById('tabMore').addEventListener('click', (event) => {
  event.stopPropagation()
  if (state.scenario !== 'pentest') return
  const show = infoButton.hidden
  infoButton.hidden = !show
  assetsButton.hidden = !show
  document.getElementById('tabMore').classList.toggle('active', show)
})
document.addEventListener('click', (event) => {
  if (!event.target.closest('#tabMore') && !event.target.closest('#infoButton') && !event.target.closest('#assetsButton')) {
    if (infoButton && !infoButton.hidden) {
      infoButton.hidden = true
      assetsButton.hidden = true
      document.getElementById('tabMore').classList.remove('active')
    }
  }
})

document.getElementById('searchBtn').addEventListener('click', () => {
  sessionSearch.hidden = !sessionSearch.hidden
  if (!sessionSearch.hidden) sessionSearch.focus()
  else {
    sessionSearch.value = ''
    filterSessions()
  }
})
sessionSearch.addEventListener('input', filterSessions)
workdirChip.addEventListener('click', (event) => {
  event.stopPropagation()
  accessPop.hidden = true
  if (approvalPop.hidden) positionApprovalPop()
  approvalPop.hidden = !approvalPop.hidden
})

scenarioChip.addEventListener('click', (event) => {
  event.stopPropagation()
  if (scenarioPop.hidden) {
    positionScenarioPop()
    loadScenarios()   // 每次打开都刷新锁定状态（发出第一条消息后就该变灰）
  }
  scenarioPop.hidden = !scenarioPop.hidden
})

contextStat.addEventListener('click', (event) => {
  event.stopPropagation()
  const show = contextPop.hidden
  closeStatPops(contextPop)
  contextPop.hidden = !show
  if (!contextPop.hidden) {
    loadContext()
    positionContextPop()
  }
})
contextPop.addEventListener('click', (event) => event.stopPropagation())

turnStat.addEventListener('click', (event) => {
  event.stopPropagation()
  const show = turnPop.hidden
  closeStatPops(turnPop)
  turnPop.hidden = !show
  if (!turnPop.hidden) {
    renderTurnPop()
    positionStatsPop(turnPop, turnStat)
  }
})
turnPop.addEventListener('click', (event) => event.stopPropagation())

tokenStat.addEventListener('click', (event) => {
  event.stopPropagation()
  const show = usagePop.hidden
  closeStatPops(usagePop)
  usagePop.hidden = !show
  if (!usagePop.hidden) {
    renderUsagePop()
    positionStatsPop(usagePop, tokenStat)
  }
})
usagePop.addEventListener('click', (event) => event.stopPropagation())

approvalPop.addEventListener('click', (event) => {
  const mode = event.target.closest('button')?.dataset.mode
  if (!mode) return
  approvalPop.hidden = true
  setApproval(mode)
})

accessPop.addEventListener('click', async (event) => {
  const outside = event.target.closest('button')?.dataset.outsideAuto
  if (outside) {
    state.outsideAuto = !state.outsideAuto
    syncModelUI()
    await saveSetting({
      sandbox_workspace: !state.outsideAuto,
      auto_allow_outside: false,
    })
    toast(state.outsideAuto
      ? '工作区外访问：自动允许'
      : '工作区外访问：仅工作区，越界会弹授权')
    return
  }
  const access = event.target.closest('button')?.dataset.access
  if (!access) return
  accessPop.hidden = true
  setAccess(access)
})
accessChip.addEventListener('click', (event) => {
  event.stopPropagation()
  approvalPop.hidden = true
  if (accessPop.hidden) positionAccessPop()
  accessPop.hidden = !accessPop.hidden
})

document.getElementById('scopeCancel').addEventListener('click', closeScopeDialog)
document.getElementById('scopeSave').addEventListener('click', saveScope)
scopeMask.addEventListener('click', (event) => {
  if (event.target === scopeMask) closeScopeDialog()
})
scopeInput.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeScopeDialog()
  }
})
document.getElementById('openConfig').addEventListener('click', () => openTarget('config', '配置文件'))
document.getElementById('openSessions').addEventListener('click', () => openTarget('sessions', '对话目录'))
document.getElementById('browserCheck').addEventListener('click', loadBrowserStatus)

document.getElementById('addProvider').addEventListener('click', openPresetView)
presetBack.addEventListener('click', closePresetView)
presetCustom.addEventListener('click', () => {
  openProviderForm(null, {
    id: 'custom',
    name: '',
    category: '',
    kind: 'openai',
    auth: 'key',
    base_url: '',
    models: [],
    desc: '',
    website: '',
    domain: '',
    icon: '',
    icon_file: '',
    color: '#9ca3af',
    oauth: false,
    templated: false,
    supported: true,
  })
})
presetSearch.addEventListener('input', () => {
  renderPresetCategories()
  renderPresetGrid()
})
presetChange.addEventListener('click', () => {
  if (!confirmProviderDiscard()) return
  openPresetView()
})
pfCancel.addEventListener('click', () => closeProviderForm())
pfSave.addEventListener('click', saveProviderForm)
pfDelete.addEventListener('click', deleteProvider)
pfFetchModels.addEventListener('click', fetchProviderModels)
pfCheck.addEventListener('click', checkProviderForm)
pfSpeedTest.addEventListener('click', speedTestForm)
pfIconPick.addEventListener('click', openIconPicker)
pfIconClear.addEventListener('click', () => {
  state.formIcon = ''
  state.providerDirty = true
  syncIconPreview()
})
pfIconColor.addEventListener('input', () => {
  state.formIconColor = pfIconColor.value
  state.providerDirty = true
  pfIconPreview.style.background = state.formIconColor
})
for (const field of [pfNotes, pfWebsite, pfEndpoints, pfCategory]) {
  field.addEventListener('input', () => { state.providerDirty = true })
  field.addEventListener('change', () => { state.providerDirty = true })
}
pfName.addEventListener('input', () => {
  if (!state.formIcon) syncIconPreview()
})
providerSearch.addEventListener('input', () => {
  state.providerSearch = providerSearch.value
  renderProviders()
})
providerExport.addEventListener('click', openProviderExport)
providerImport.addEventListener('click', openProviderImport)
providerIoCancel.addEventListener('click', () => { providerIoMask.hidden = true })
providerIoOk.addEventListener('click', providerIoSubmit)
providerIoCopy.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(providerIoText.value)
    toast('已复制')
  } catch {
    providerIoText.select()
    toast('复制失败，已全选，按 Ctrl+C')
  }
})
iconSearch.addEventListener('input', renderIconGrid)
iconClose.addEventListener('click', () => { iconMask.hidden = true })
modelFilter.addEventListener('input', renderModelPicker)
modelClose.addEventListener('click', () => { modelPicker.hidden = true })
pfModels.addEventListener('input', () => {
  state.providerDirty = true
  syncModelSelectionFromInput()
})
for (const field of [pfName, pfKind, pfAuth, pfBaseUrl, pfKey, pfPriceIn, pfPriceOut, pfPriceCached, pfCurrency, pfContextWindow, pfMaxTokens, pfFailover]) {
  field.addEventListener('input', () => { state.providerDirty = true })
  field.addEventListener('change', () => { state.providerDirty = true })
}
pfKind.addEventListener('change', () => {
  pfAuthRow.hidden = pfKind.value !== 'anthropic'
})

for (const field of [limitTurnTokens, limitSessionTokens, repeatLimit]) {
  field.addEventListener('change', saveLimits)
}

failoverSwitch.addEventListener('click', async () => {
  state.failover = !state.failover
  syncModelUI()
  await saveSetting({ failover: state.failover })
  toast(state.failover
    ? '故障转移已开启（按供应商列表顺序换家）'
    : '故障转移已关闭')
})


menuPop.addEventListener('click', (event) => {
  const action = event.target.closest('button')?.dataset.action
  closeMenu()
  if (action === 'model-settings') openSettings('model')
  if (action === 'general-settings') openSettings('general')
  if (action === 'about') toast(state.build || 'Spirit 0.1.0 · Agent 通用计算机')
  if (action === 'stop-engine') {
    if (window.confirm('关机？页面将不再响应，直到重新启动。')) {
      fetch('/api/stop', { method: 'POST' }).catch(() => {})
    }
  }
})

document.getElementById('closeSettings').addEventListener('click', closeSettings)
settingsMask.addEventListener('click', (event) => {
  if (event.target === settingsMask) closeSettings()
})

for (const item of document.querySelectorAll('.settings-nav-item')) {
  item.addEventListener('click', () => {
    if (!providerForm.hidden && item.dataset.panel !== 'model' && !closeProviderForm()) {
      return
    }
    if (item.dataset.panel !== 'model') resetProviderView()
    selectSettingsPanel(item.dataset.panel)
  })
}

themeSeg.addEventListener('click', (event) => {
  const btn = event.target.closest('button')
  if (!btn) return
  prefs.theme = btn.dataset.value
  savePrefs()
  applyPrefs()
})

fontSeg.addEventListener('click', (event) => {
  const btn = event.target.closest('button')
  if (!btn) return
  prefs.fontSize = btn.dataset.value
  savePrefs()
  applyPrefs()
})

effortSeg.addEventListener('click', (event) => {
  const btn = event.target.closest('button')
  if (!btn) return
  setEffort(btn.dataset.value)
})

untrustedSeg.addEventListener('click', async (event) => {
  const btn = event.target.closest('button')
  if (!btn) return
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ untrusted_policy: btn.dataset.value }),
    }).then((r) => r.json())
    if (!res.ok) {
      toast(res.error || '保存失败')
      return
    }
    state.untrusted = res.untrusted_policy
    markSegmented(untrustedSeg, state.untrusted)
    const label = { warn: '仅审计', confirm: '确认', block: '阻止' }[state.untrusted]
    toast(`不可信内容之后：${label}`)
  } catch {
    toast('保存失败')
  }
})

thinkingSwitch.addEventListener('click', toggleThinking)

modelPill.addEventListener('click', (event) => {
  event.stopPropagation()
  togglePopover()
})

document.getElementById('popEffort').addEventListener('click', (event) => {
  event.stopPropagation()
  const index = EFFORTS.indexOf(state.effort)
  setEffort(EFFORTS[(index + 1) % EFFORTS.length])
})

document.getElementById('popThinking').addEventListener('click', (event) => {
  event.stopPropagation()
  toggleThinking()
})

document.getElementById('popModel').addEventListener('click', (event) => {
  event.stopPropagation()
  popModelList.hidden = !popModelList.hidden
  if (!popModelList.hidden) positionPopover()
})

document.addEventListener('click', (event) => {
  togglePopover(false)
  approvalPop.hidden = true
  accessPop.hidden = true
  scenarioPop.hidden = true
  closeStatPops()
  closeMenu()
  if (!event.target.closest('.session-menu') && !event.target.closest('.session-more')) {
    closeSessionMenu()
  }
})
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    togglePopover(false)
    approvalPop.hidden = true
    accessPop.hidden = true
    scenarioPop.hidden = true
    providerIoMask.hidden = true
    iconMask.hidden = true
    closeStatPops()
    closeSettings()
    closeMenu()
    closeSessionMenu()
  }
  // 照抄 cc-switch：设置页里 Ctrl/Cmd+F 直接跳到供应商搜索
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'f') {
    if (!settingsMask.hidden && !providerListView.hidden) {
      event.preventDefault()
      providerSearch.focus()
      providerSearch.select()
    }
  }
})

/* ---------- 启动 ---------- */
async function bootstrap() {
  await loadSessions()
  try {
    const data = await fetch(sessionUrl(`/api/history?limit=${state.historyLimit}`))
      .then((res) => res.json())
    const events = data.events || []
    if (events.length || data.has_more) {
      renderHistory(events, data)
      const first = sessionList.querySelector('.session-item')
      if (first) {
        state.currentSession = first.dataset.path || null
        state.sessionId = first.dataset.session || 'primary'
        markActive(state.sessionId)
        setTitle(first.dataset.title || first.querySelector('.title').textContent)
      }
    }
  } catch { /* 无历史 */ }
}

if (DESKTOP) {
  document.body.classList.add('desktop')
  titlebarEl.hidden = false
}
applyPrefs()
resize()
updateSendButton()
shell.classList.add('hero')
loadSettings()
loadScope()
loadProviders()
loadUsage()
loadContext()
loadScenarios()
bootstrap()
checkRenderHealth()
setInterval(checkRenderHealth, 5000)
