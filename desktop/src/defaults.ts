/** 首次启动写进 data/config.json 的默认配置。 */
export const DEFAULT_CONFIG = {
  llm: {
    provider: 'openai',
    provider_id: 'deepseek',
    model: 'deepseek-Flash',
    base_url: 'https://api.deepseek.com',
    api_key: '',
    api_key_env: 'DEEPSEEK_API_KEY',
    providers: [
      {
        id: 'deepseek',
        name: 'DeepSeek',
        kind: 'openai',
        auth: 'token',
        category: 'cn_official',
        base_url: 'https://api.deepseek.com',
        endpoints: ['https://api.deepseek.com'],
        api_key: '',
        api_key_env: 'DEEPSEEK_API_KEY',
        api_key_url: 'https://platform.deepseek.com/api_keys',
        models: ['deepseek-Flash', 'deepseek-v4-flash'],
        pricing: { input: 0, output: 0, currency: 'CNY' },
        website: 'https://platform.deepseek.com',
        notes: '',
        icon: 'deepseek.svg',
        icon_color: '#4d6bfe',
        in_failover_queue: false,
        context_window: 128000,
        max_tokens: 8192,
      },
    ],
    pricing: { input: 0, output: 0, currency: 'CNY' },
    reasoning: 'high',
    context_window: 128000,
    search_provider: 'deepseek',
    search_base_url: 'https://api.deepseek.com/anthropic/v1',
    search_model: 'deepseek-v4-flash',
    tavily_api_key: '',
    tavily_api_key_env: 'TAVILY_API_KEY',
  },
  engine: {
    // 0 = 不设人为步数上限；只靠“停止 / 重复拦截 / 预算”兜底（高强度设计前提）
    max_steps: 0,
    thinking: false,
    restore: true,
    system_prompt: '',
    system_prompt_file: 'Prompts/engine.md',
    scenario: 'daily',
    project_context: '',
    tool_output_inline: 12000,
    bash_timeout: 30,
    keep_recent_tool_results: 5,
    summarize: true,
    keep_recent_turns: 2,
    tool_workers: 4,
    capability_timeout: 60,
    access: 'workspace',
    approval: 'auto',
    approval_timeout: 30,
    untrusted_policy: 'confirm',
    max_turn_tokens: 0,
    max_session_tokens: 0,
    max_turn_cost: 0,
    max_session_cost: 0,
    repeat_limit: 3,
    sandbox: {
      // 默认不限制在工作区：是否用沙箱由模型通过 sandbox_run 自己决定
      workspace_only: false,
      allow_paths: [],
      deny_paths: [
        '~/.ssh',
        '~/.aws',
        '~/.gnupg',
        '~/.git-credentials',
        '~/.npmrc',
        '~/.docker/config.json',
      ],
      deny_parent_escape: true,
      home_is_workspace: true,
      scrub_env: true,
      deny_commands: [
        '\\brm\\s+(-\\S+\\s+)*[/~]',
        '\\bmkfs(\\.|\\s)',
        '\\bdiskpart\\b',
        '\\bformat\\s+[a-z]:',
        ':\\(\\)\\s*\\{\\s*:\\s*\\|\\s*:\\s*&\\s*\\}\\s*;\\s*:',
        '\\bshutdown\\s+[/-]',
      ],
    },
    workdir: '',
    default_workspace: '',
    workspaces: [],
    spill_dir: 'Session_Storage/spill',
    budget_ratio: 0.8,
    bash_path: '',
    web_host: '127.0.0.1',
    web_port: 5000,
  },
}

export const WORKSPACE_FOLDERS = [
  'scripts',
  'files',
  'images',
  'videos',
  'audio',
  'tmp',
]

export const WORKSPACE_README = `# 工作区

这是 Spirit 的默认工作目录：模型执行命令、读写文件、跑工具都从这里开始。

## 目录约定

- scripts/   模型写的脚本（.py / .sh / .ps1 等）
- files/     文档、数据、报告、下载下来的文件
- images/    图片
- videos/    视频
- audio/     音频
- tmp/       临时文件，可以随时清空

生成的东西按类型放，尽量别往工作区根目录堆；删除这些文件夹不影响 Spirit，下次启动会重建。

- 想换工作区：改 data/config.json 里的 engine.workdir（或者启动时设置 SPIRIT_WORKDIR）
`

