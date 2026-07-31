import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  Download,
  ExternalLink,
  KeyRound,
  Plus,
  RefreshCw,
  Save,
  Server,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, jsonBody, type ModelProvider } from '../api/client'
import { normaliseCodexModels, type CodexModels } from './codexModels'
import { ErrorState, LoadingState, StatusBadge } from './Common'

type ProviderPreset = {
  preset_id: string
  display_name: string
  base_url: string
  provider_kind: 'openai_compatible'
  auth_mode: 'api_key'
}

type CodexAccount = {
  account: { type?: string; email?: string | null; planType?: string | null } | null
  requiresOpenaiAuth?: boolean
}

type CodexRuntime = {
  installed: boolean
  available: boolean
  version?: string | null
  npm_available: boolean
  download_estimate_mb: number
}

export function ModelProvidersSection() {
  const queryClient = useQueryClient()
  const providers = useQuery({
    queryKey: ['model-providers'],
    queryFn: () => api<ModelProvider[]>('/api/v1/model-providers?diagnostics=true'),
  })
  const presets = useQuery({
    queryKey: ['model-provider-presets'],
    queryFn: () => api<ProviderPreset[]>('/api/v1/model-provider-presets'),
  })
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['model-providers'] })
    await queryClient.invalidateQueries({ queryKey: ['bootstrap'] })
  }
  const update = useMutation({
    mutationFn: ({ providerId, values }: { providerId: string; values: Record<string, unknown> }) => (
      api<ModelProvider>(`/api/v1/model-providers/${providerId}`, {
        method: 'PATCH',
        body: jsonBody(values),
      })
    ),
    onSuccess: refresh,
  })
  const test = useMutation({
    mutationFn: (providerId: string) => api<{ ok: boolean }>(`/api/v1/model-providers/${providerId}/test`, {
      method: 'POST',
    }),
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (providerId: string) => api(`/api/v1/model-providers/${providerId}`, {
      method: 'DELETE',
    }),
    onSuccess: refresh,
  })
  const actionError = providers.error ?? presets.error ?? update.error ?? test.error ?? remove.error
  const providerItems = Array.isArray(providers.data) ? providers.data : []
  const presetItems = Array.isArray(presets.data) ? presets.data : []

  return (
    <div className="settings-detail-stack">
      <section className="settings-detail-intro">
        <p className="eyebrow">Models</p>
        <h2>主模型与备用模型</h2>
        <p>IELTS 教学 Runtime 始终控制流程和保存；这里仅决定由哪个模型完成需要推理的步骤。</p>
      </section>

      <OpenAIProviderCard providers={providerItems} refresh={refresh} />

      <section className="settings-panel">
        <div className="section-heading">
          <div><h3>当前模型路线</h3><p>一个主模型，可以配置多个备用模型。</p></div>
        </div>
        {providers.isPending && <LoadingState label="正在读取模型配置" />}
        <div className="provider-route-list">
          {providerItems.map((provider) => (
            <article key={provider.provider_id} className={provider.role === 'primary' ? 'provider-row primary-provider' : 'provider-row'}>
              <div className="provider-row-icon"><Server size={18} /></div>
              <div className="provider-row-copy">
                <div>
                  <strong>{provider.display_name}</strong>
                  <StatusBadge tone={provider.role === 'primary' ? 'success' : provider.role === 'fallback' ? 'warning' : 'neutral'}>
                    {provider.role === 'primary' ? '主模型' : provider.role === 'fallback' ? '备用' : '未启用'}
                  </StatusBadge>
                </div>
                <p>{provider.model_id ?? '尚未选择模型'}{provider.base_url ? ` · ${provider.base_url}` : ''}</p>
              </div>
              <div className="provider-row-actions">
                {provider.role !== 'primary' && (
                  <button
                    className="button secondary"
                    onClick={() => update.mutate({ providerId: provider.provider_id, values: { role: 'primary' } })}
                    disabled={!provider.available || update.isPending}
                  >
                    设为主模型
                  </button>
                )}
                {provider.role === 'disabled' && (
                  <button
                    className="button ghost"
                    onClick={() => update.mutate({ providerId: provider.provider_id, values: { role: 'fallback' } })}
                    disabled={!provider.available || update.isPending}
                  >
                    设为备用
                  </button>
                )}
                {provider.role === 'fallback' && (
                  <button
                    className="button ghost"
                    onClick={() => update.mutate({ providerId: provider.provider_id, values: { role: 'disabled' } })}
                    disabled={update.isPending}
                  >
                    停用
                  </button>
                )}
                {provider.provider_kind !== 'codex_oauth_bridge' && (
                  <>
                    <button className="icon-button" title="测试连接" aria-label={`测试 ${provider.display_name} 连接`} onClick={() => test.mutate(provider.provider_id)} disabled={test.isPending}>
                      <RefreshCw size={16} aria-hidden="true" />
                    </button>
                    <button
                      className="icon-button danger"
                      title="删除连接"
                      aria-label={`删除 ${provider.display_name} 连接`}
                      onClick={() => {
                        if (window.confirm(`删除“${provider.display_name}”连接？`)) {
                          remove.mutate(provider.provider_id)
                        }
                      }}
                      disabled={provider.role === 'primary' || remove.isPending}
                    >
                      <Trash2 size={16} aria-hidden="true" />
                    </button>
                  </>
                )}
              </div>
            </article>
          ))}
        </div>
        {test.isSuccess && <p className="inline-success"><Check size={16} />连接测试通过。</p>}
      </section>

      <CustomProviderForm
        presets={presetItems}
        hasPrimary={providerItems.some((item) => item.role === 'primary')}
        refresh={refresh}
      />
      {actionError && <ErrorState error={actionError} />}
    </div>
  )
}

function OpenAIProviderCard({ providers, refresh }: {
  providers: ModelProvider[]
  refresh: () => Promise<void>
}) {
  const openai = providers.find((item) => item.provider_id === 'openai-codex-oauth')
  const [modelId, setModelId] = useState('')
  const [effort, setEffort] = useState('')
  useEffect(() => {
    setModelId(openai?.model_id ?? '')
    setEffort(openai?.reasoning_effort ?? '')
  }, [openai])
  const runtime = useQuery({
    queryKey: ['codex-managed-runtime'],
    queryFn: () => api<CodexRuntime>('/api/v1/execution-profiles/codex-managed/runtime'),
    retry: false,
  })
  const account = useQuery({
    queryKey: ['codex-managed-account'],
    queryFn: () => api<CodexAccount>('/api/v1/execution-profiles/codex-managed/account'),
    enabled: Boolean(runtime.data?.installed),
    retry: false,
    refetchInterval: runtime.data?.installed ? 5_000 : false,
  })
  const signedIn = Boolean(account.data?.account) || account.data?.requiresOpenaiAuth === false
  const models = useQuery({
    queryKey: ['codex-managed-models'],
    queryFn: () => api<CodexModels>('/api/v1/execution-profiles/codex-managed/models'),
    enabled: signedIn,
    retry: false,
  })
  const options = useMemo(() => normaliseCodexModels(models.data), [models.data])
  const selected = options.find((item) => (item.id ?? item.model) === modelId)
  const efforts = selected?.supportedReasoningEfforts.length
    ? selected.supportedReasoningEfforts
    : ['low', 'medium', 'high']
  useEffect(() => {
    if (modelId || options.length === 0) return
    const defaultModel = options.find((item) => item.isDefault) ?? options[0]
    setModelId(defaultModel.id ?? defaultModel.model ?? '')
    if (!effort && defaultModel.defaultReasoningEffort) {
      setEffort(defaultModel.defaultReasoningEffort)
    }
  }, [effort, modelId, options])
  const install = useMutation({
    mutationFn: () => api<CodexRuntime>('/api/v1/execution-profiles/codex-managed/runtime/install', { method: 'POST' }),
    onSuccess: refresh,
  })
  const login = useMutation({
    mutationFn: () => api<{ authUrl?: string }>('/api/v1/execution-profiles/codex-managed/login', {
      method: 'POST',
      body: jsonBody({ login_type: 'chatgpt' }),
    }),
    onSuccess: async (result) => {
      if (result.authUrl) window.open(result.authUrl, '_blank', 'noopener,noreferrer')
      await refresh()
    },
  })
  const save = useMutation({
    mutationFn: () => api(`/api/v1/model-providers/openai-codex-oauth`, {
      method: 'PATCH',
      body: jsonBody({
        model_id: modelId || null,
        reasoning_effort: effort || null,
        role: 'primary',
      }),
    }),
    onSuccess: refresh,
  })
  const error = runtime.error ?? account.error ?? models.error ?? install.error ?? login.error ?? save.error

  return (
    <section className="settings-panel recommended-provider">
      <div className="recommended-label">推荐</div>
      <div className="section-heading">
        <div>
          <h3>使用 ChatGPT 登录</h3>
          <p>无需复制 API Key；登录凭据只属于本机 IELTS Study Desk。</p>
        </div>
        <StatusBadge tone={signedIn ? 'success' : runtime.data?.installed ? 'warning' : 'neutral'}>
          {signedIn
            ? openai?.role === 'primary'
              ? '当前主模型'
              : openai?.role === 'fallback'
                ? '已登录 · 备用'
                : '已登录 · 未启用'
            : runtime.data?.installed
              ? '等待登录'
              : '未安装'}
        </StatusBadge>
      </div>
      {!runtime.data?.installed ? (
        <button className="button primary" onClick={() => install.mutate()} disabled={install.isPending || runtime.data?.npm_available === false}>
          {install.isPending ? <><RefreshCw className="spin" size={16} />正在安装</> : <><Download size={16} />安装登录组件</>}
        </button>
      ) : !signedIn ? (
        <button className="button primary" onClick={() => login.mutate()} disabled={login.isPending}>
          <ExternalLink size={16} />使用 ChatGPT 登录
        </button>
      ) : (
        <>
          {models.isPending && <LoadingState label="正在读取可用模型" />}
          <div className="model-choice-row">
            <label>模型
              <select value={modelId} onChange={(event) => setModelId(event.target.value)}>
                <option value="">使用默认模型</option>
                {options.map((item) => {
                  const value = item.id ?? item.model ?? ''
                  return <option key={value} value={value}>{item.displayName ?? value}</option>
                })}
              </select>
            </label>
            <label>推理强度
              <select value={effort} onChange={(event) => setEffort(event.target.value)}>
                <option value="">默认</option>
                {efforts.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </label>
            <button className="button primary" onClick={() => save.mutate()} disabled={save.isPending}>
              <Save size={16} />保存并设为主模型
            </button>
          </div>
          <p className="muted">账号：{account.data?.account?.email ?? account.data?.account?.type ?? 'ChatGPT'} · {runtime.data?.version ?? 'Codex runtime'}</p>
          {openai?.role === 'disabled' && !models.isPending && !models.error && (
            <p className="inline-success"><Check size={16} />登录和模型列表连接正常；保存后即可用于 IELTS 教学任务。</p>
          )}
        </>
      )}
      {error && <ErrorState error={error} />}
    </section>
  )
}

function CustomProviderForm({ presets, hasPrimary, refresh }: {
  presets: ProviderPreset[]
  hasPrimary: boolean
  refresh: () => Promise<void>
}) {
  const [presetId, setPresetId] = useState('custom')
  const [displayName, setDisplayName] = useState('自定义 API')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelId, setModelId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const create = useMutation({
    mutationFn: () => api<ModelProvider>('/api/v1/model-providers', {
      method: 'POST',
      body: jsonBody({
        provider_id: `api-${crypto.randomUUID().slice(0, 8)}`,
        display_name: displayName,
        provider_kind: 'openai_compatible',
        base_url: baseUrl,
        model_id: modelId,
        auth_mode: 'api_key',
        api_key: apiKey,
        role: hasPrimary ? 'fallback' : 'primary',
        config: {},
      }),
    }),
    onSuccess: async () => {
      setApiKey('')
      await refresh()
    },
  })
  function choosePreset(value: string) {
    setPresetId(value)
    const preset = presets.find((item) => item.preset_id === value)
    if (preset) {
      setDisplayName(preset.display_name)
      setBaseUrl(preset.base_url)
    } else {
      setDisplayName('自定义 API')
      setBaseUrl('')
    }
  }
  return (
    <section className="settings-panel">
      <div className="section-heading">
        <div><h3>使用自己的 API</h3><p>统一使用 OpenAI-compatible 协议；密钥不会写入学习数据库。</p></div>
        <KeyRound size={19} />
      </div>
      <div className="provider-form-grid">
        <label>服务预设
          <select value={presetId} onChange={(event) => choosePreset(event.target.value)}>
            <option value="custom">自定义</option>
            {presets.map((item) => <option key={item.preset_id} value={item.preset_id}>{item.display_name}</option>)}
          </select>
        </label>
        <label>连接名称<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
        <label className="wide-field">Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label>
        <label>Model ID<input value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="provider-model-id" /></label>
        <label>API Key<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
      </div>
      <button className="button secondary" onClick={() => create.mutate()} disabled={!baseUrl || !modelId || !apiKey || create.isPending}>
        <Plus size={16} />保存为{hasPrimary ? '备用模型' : '主模型'}
      </button>
      {create.error && <ErrorState error={create.error} />}
    </section>
  )
}
