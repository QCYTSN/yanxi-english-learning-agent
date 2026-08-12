import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Copy,
  Download,
  ExternalLink,
  KeyRound,
  LogOut,
  PlugZap,
  RefreshCw,
  Save,
  ShieldCheck,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, jsonBody, type ExecutionProfile } from '../api/client'
import { ErrorState, LoadingState, StatusBadge } from './Common'

type CodexAccount = {
  account: { type?: string; email?: string | null; planType?: string | null } | null
  authMode?: string | null
  requiresOpenaiAuth?: boolean
}

type CodexModel = {
  id?: string
  model?: string
  displayName?: string
  supportedReasoningEfforts?: string[]
}

type CodexModels = {
  data?: CodexModel[]
  models?: CodexModel[]
}

type ManagedCodexRuntime = {
  installed: boolean
  available: boolean
  package: string
  pinned_version: string
  version?: string | null
  executable_path?: string | null
  install_root: string
  npm_available: boolean
  download_estimate_mb: number
  installed_size_estimate_mb: number
  isolated_auth_home: string
  shares_global_codex_auth: boolean
}

type CodexLoginResult = {
  authUrl?: string
  loginId?: string
  verificationUrl?: string
  userCode?: string
}

export function AIConnectionsSection() {
  const queryClient = useQueryClient()
  const profiles = useQuery({
    queryKey: ['execution-profiles'],
    queryFn: () => api<ExecutionProfile[]>('/api/v1/execution-profiles'),
  })
  const codex = profiles.data?.find((profile) => profile.profile_id === 'codex-managed')
  const [executablePath, setExecutablePath] = useState('')
  const [modelId, setModelId] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [authUrl, setAuthUrl] = useState('')
  const [deviceLogin, setDeviceLogin] = useState<CodexLoginResult | null>(null)

  useEffect(() => {
    if (!codex) return
    setExecutablePath(codex.config.executable_path ?? '')
    setModelId(codex.model_id ?? '')
    setReasoningEffort(codex.reasoning_effort ?? '')
  }, [codex])

  const runtime = useQuery({
    queryKey: ['codex-managed-runtime'],
    queryFn: () => api<ManagedCodexRuntime>('/api/v1/execution-profiles/codex-managed/runtime'),
    enabled: Boolean(codex),
    retry: false,
  })
  const callable = Boolean(codex?.available)
  const account = useQuery({
    queryKey: ['codex-managed-account'],
    queryFn: () => api<CodexAccount>('/api/v1/execution-profiles/codex-managed/account'),
    enabled: callable,
    retry: false,
    refetchInterval: callable ? 5_000 : false,
  })
  const signedIn = Boolean(account.data?.account) || account.data?.requiresOpenaiAuth === false
  const models = useQuery({
    queryKey: ['codex-managed-models'],
    queryFn: () => api<CodexModels>('/api/v1/execution-profiles/codex-managed/models'),
    enabled: callable && signedIn,
    retry: false,
  })
  const modelOptions = useMemo(
    () => models.data?.data ?? models.data?.models ?? [],
    [models.data],
  )
  const selectedModel = modelOptions.find((item) => (item.id ?? item.model) === modelId)
  const effortOptions = selectedModel?.supportedReasoningEfforts ?? ['low', 'medium', 'high']

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['execution-profiles'] })
    await queryClient.invalidateQueries({ queryKey: ['codex-managed-runtime'] })
    await queryClient.invalidateQueries({ queryKey: ['codex-managed-account'] })
    await queryClient.invalidateQueries({ queryKey: ['codex-managed-models'] })
  }
  const installRuntime = useMutation({
    mutationFn: () => api<ManagedCodexRuntime>('/api/v1/execution-profiles/codex-managed/runtime/install', {
      method: 'POST',
    }),
    onSuccess: refresh,
  })
  const save = useMutation({
    mutationFn: () => api<ExecutionProfile>('/api/v1/execution-profiles/codex-managed', {
      method: 'PATCH',
      body: jsonBody({
        model_id: modelId || null,
        reasoning_effort: reasoningEffort || null,
        config: { executable_path: executablePath || null },
      }),
    }),
    onSuccess: refresh,
  })
  const makeDefault = useMutation({
    mutationFn: () => api<ExecutionProfile>('/api/v1/execution-profiles/codex-managed', {
      method: 'PATCH',
      body: jsonBody({
        is_default: true,
        model_id: modelId || null,
        reasoning_effort: reasoningEffort || null,
        config: { executable_path: executablePath || null },
      }),
    }),
    onSuccess: refresh,
  })
  const loginChatGPT = useMutation({
    mutationFn: () => api<CodexLoginResult>('/api/v1/execution-profiles/codex-managed/login', {
      method: 'POST',
      body: jsonBody({ login_type: 'chatgpt' }),
    }),
    onSuccess: async (result) => {
      if (result.authUrl) {
        setAuthUrl(result.authUrl)
        window.open(result.authUrl, '_blank', 'noopener,noreferrer')
      }
      await refresh()
    },
  })
  const loginDeviceCode = useMutation({
    mutationFn: () => api<CodexLoginResult>('/api/v1/execution-profiles/codex-managed/login', {
      method: 'POST',
      body: jsonBody({ login_type: 'chatgptDeviceCode' }),
    }),
    onSuccess: async (result) => {
      setDeviceLogin(result)
      if (result.verificationUrl) {
        window.open(result.verificationUrl, '_blank', 'noopener,noreferrer')
      }
      await refresh()
    },
  })
  const loginApiKey = useMutation({
    mutationFn: () => api('/api/v1/execution-profiles/codex-managed/login', {
      method: 'POST',
      body: jsonBody({ login_type: 'apiKey', api_key: apiKey }),
    }),
    onSuccess: refresh,
    onSettled: () => setApiKey(''),
  })
  const logout = useMutation({
    mutationFn: () => api('/api/v1/execution-profiles/codex-managed/logout', { method: 'POST' }),
    onSuccess: refresh,
  })
  const actionError = profiles.error ?? runtime.error ?? account.error ?? models.error ?? save.error
    ?? installRuntime.error ?? makeDefault.error ?? loginChatGPT.error
    ?? loginDeviceCode.error ?? loginApiKey.error ?? logout.error

  return (
    <section className="settings-section" id="ai-connections">
      <div className="section-heading">
        <div><p className="eyebrow">AI Connections</p><h2>模型连接与执行身份</h2></div>
        <StatusBadge tone={signedIn ? 'success' : callable ? 'warning' : 'neutral'}>
          {signedIn ? 'OpenAI 已连接' : callable ? '等待登录' : '尚未安装'}
        </StatusBadge>
      </div>
      <p>
        系统可以按需安装一套隔离的官方 OpenAI Codex 运行时，然后使用你的 ChatGPT 账号登录。
        这套登录只属于 IELTS AI Coach，不读取或修改其他终端的 Codex 配置。
      </p>
      {profiles.isPending && <LoadingState label="正在检查本地模型连接" />}
      {codex && (
        <article className="connection-card">
          <div className="connection-card-heading">
            <div>
              <h3>OpenAI Codex</h3>
              <p>
                官方 Codex app-server · {account.data?.account?.email ?? account.data?.account?.type ?? '未登录'}
                {account.data?.account?.planType ? ` · ${account.data.account.planType}` : ''}
              </p>
            </div>
            {codex.is_default && <StatusBadge tone="success">默认执行方式</StatusBadge>}
          </div>

          {!runtime.data?.installed && (
            <div className="runtime-install-card">
              <div className="runtime-install-icon"><Download size={21} /></div>
              <div>
                <strong>安装官方 OpenAI Codex 运行时</strong>
                <p>
                  首次使用需要约 {runtime.data?.download_estimate_mb ?? 150} MB 下载，
                  安装后约占 {runtime.data?.installed_size_estimate_mb ?? 430} MB。
                  运行时与登录凭据都只保存在本机 IELTS 数据目录。
                </p>
                {runtime.data && !runtime.data.npm_available && (
                  <p className="import-error">
                    没有找到 npm。请先安装 Node.js，或在下方高级设置中指定独立 Codex CLI。
                  </p>
                )}
              </div>
              <button
                className="button primary"
                onClick={() => installRuntime.mutate()}
                disabled={installRuntime.isPending || runtime.isPending || runtime.data?.npm_available === false}
              >
                {installRuntime.isPending
                  ? <><RefreshCw className="spin" size={16} />正在安装，可能需要几分钟</>
                  : <><Download size={16} />安装并启用登录</>}
              </button>
            </div>
          )}

          {runtime.data?.installed && (
            <div className="runtime-ready">
              <ShieldCheck size={18} />
              <span>
                官方运行时已就绪 · {runtime.data.version ?? runtime.data.pinned_version}
                <small>不会共享或覆盖全局 Codex 登录</small>
              </span>
            </div>
          )}

          {callable && !signedIn && (
            <div className="openai-login-panel">
              <div>
                <strong>使用 OpenAI / ChatGPT 登录</strong>
                <p>浏览器完成授权后，本页会自动识别账号并加载可用模型。</p>
              </div>
              <div className="row-actions">
                <button
                  className="button primary"
                  onClick={() => loginChatGPT.mutate()}
                  disabled={loginChatGPT.isPending}
                >
                  <ExternalLink size={16} />打开登录页面
                </button>
                <button
                  className="button secondary"
                  onClick={() => loginDeviceCode.mutate()}
                  disabled={loginDeviceCode.isPending}
                >
                  <KeyRound size={16} />改用设备码
                </button>
              </div>
            </div>
          )}

          {authUrl && !signedIn && (
            <p className="auth-followup">
              如果登录页没有自动打开，
              <a href={authUrl} target="_blank" rel="noreferrer">请点此继续登录</a>。
              完成后本页会自动刷新连接状态。
            </p>
          )}

          {deviceLogin?.userCode && !signedIn && (
            <div className="device-code-panel">
              <div>
                <span>设备码</span>
                <strong>{deviceLogin.userCode}</strong>
              </div>
              <button
                className="button secondary"
                onClick={() => void navigator.clipboard.writeText(deviceLogin.userCode ?? '')}
              >
                <Copy size={16} />复制
              </button>
              {deviceLogin.verificationUrl && (
                <a
                  className="button secondary"
                  href={deviceLogin.verificationUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink size={16} />打开验证页
                </a>
              )}
            </div>
          )}

          <div className="handoff-options">
            <label>
              模型
              <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
                <option value="">使用 Codex 默认模型</option>
                {modelOptions.map((item) => {
                  const value = item.id ?? item.model ?? ''
                  return <option key={value} value={value}>{item.displayName ?? value}</option>
                })}
              </select>
            </label>
            <label>
              推理强度
              <select value={reasoningEffort} onChange={(event) => setReasoningEffort(event.target.value)}>
                <option value="">使用模型默认值</option>
                {effortOptions.map((effort) => <option key={effort} value={effort}>{effort}</option>)}
              </select>
            </label>
          </div>

          <div className="row-actions">
            <button className="button secondary" onClick={() => save.mutate()} disabled={save.isPending}>
              <Save size={16} />保存运行配置
            </button>
            {!codex.is_default && (
              <button
                className="button secondary"
                onClick={() => makeDefault.mutate()}
                disabled={!callable || makeDefault.isPending}
              >
                <PlugZap size={16} />设为默认
              </button>
            )}
            {signedIn && (
              <button className="button secondary" onClick={() => models.refetch()} disabled={models.isFetching}>
                <RefreshCw size={16} />刷新模型
              </button>
            )}
            {signedIn && (
              <button className="button ghost" onClick={() => logout.mutate()} disabled={logout.isPending}>
                <LogOut size={16} />退出此系统的 Codex
              </button>
            )}
          </div>

          {!callable && (
            <p className="import-error">
              {codex.diagnostics?.boundary ?? '尚未找到可由本地服务启动的 Codex 运行时。'}
            </p>
          )}
          {codex.diagnostics?.executable_path && (
            <small>
              <code>{codex.diagnostics.executable_path}</code> · {codex.diagnostics.version ?? '版本未知'}
            </small>
          )}
          {codex.diagnostics?.isolated_codex_home && (
            <p className="muted">独立登录目录：<code>{codex.diagnostics.isolated_codex_home}</code></p>
          )}

          <details>
            <summary>高级运行时设置</summary>
            <div className="handoff-options advanced-runtime-fields">
              <label>
                独立 Codex CLI 可执行文件（可选）
                <input
                  value={executablePath}
                  onChange={(event) => setExecutablePath(event.target.value)}
                  placeholder="留空则优先使用本系统安装的官方运行时"
                />
              </label>
            </div>
          </details>

          {callable && !signedIn && (
            <details>
              <summary>改用 API Key</summary>
              <div className="manual-identity-fields">
                <label>
                  API Key
                  <input
                    type="password"
                    autoComplete="off"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder="只发送给独立 Codex 运行时，不写入 IELTS 数据库"
                  />
                </label>
                <button
                  className="button secondary"
                  disabled={!apiKey || loginApiKey.isPending}
                  onClick={() => loginApiKey.mutate()}
                >
                  <KeyRound size={16} />连接
                </button>
              </div>
            </details>
          )}
        </article>
      )}

      {actionError && <ErrorState error={actionError} />}
    </section>
  )
}
