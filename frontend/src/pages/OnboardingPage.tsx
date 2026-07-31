import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, CheckCircle2, Download, ExternalLink, KeyRound, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { api, jsonBody, type Bootstrap } from '../api/client'
import { ErrorState, PageHeader } from '../components/Common'

const modules = ['listening', 'reading', 'writing', 'speaking'] as const

export function OnboardingPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const queryClient = useQueryClient()
  const profile = bootstrap.profile
  const [academicConfirmed, setAcademicConfirmed] = useState(false)
  const [testDate, setTestDate] = useState(profile?.test_date ?? '')
  const [target, setTarget] = useState<Record<string, number | null>>({ ...(profile?.target ?? {}) })
  const [minimum, setMinimum] = useState<Record<string, number | null>>({ ...(profile?.minimum_required ?? {}) })
  const [current, setCurrent] = useState<Record<string, number | null>>({ ...(profile?.current ?? {}) })
  const [privacy, setPrivacy] = useState<Record<string, boolean>>({
    allow_private_corpus: profile?.privacy.allow_private_corpus ?? true,
    allow_cloud_upload: profile?.privacy.allow_cloud_upload ?? false,
    store_raw_voice_audio: profile?.privacy.store_raw_voice_audio ?? false,
  })
  const [next, setNext] = useState<'today' | 'diagnostic'>('today')
  const existingPrimary = bootstrap.model_providers?.find((item) => item.role === 'primary')
  const [aiChoice, setAiChoice] = useState<'oauth' | 'api' | 'later'>(
    existingPrimary?.provider_kind === 'codex_oauth_bridge'
      ? 'oauth'
      : existingPrimary
        ? 'later'
        : 'oauth',
  )
  const [apiName, setApiName] = useState('自定义 API')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelId, setModelId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const runtime = useQuery({
    queryKey: ['codex-managed-runtime'],
    queryFn: () => api<{ installed: boolean; npm_available: boolean; download_estimate_mb: number }>('/api/v1/execution-profiles/codex-managed/runtime'),
    enabled: aiChoice === 'oauth',
    retry: false,
  })
  const account = useQuery({
    queryKey: ['codex-managed-account'],
    queryFn: () => api<{ account: Record<string, unknown> | null; requiresOpenaiAuth?: boolean }>('/api/v1/execution-profiles/codex-managed/account'),
    enabled: aiChoice === 'oauth' && Boolean(runtime.data?.installed),
    retry: false,
    refetchInterval: aiChoice === 'oauth' && runtime.data?.installed ? 4_000 : false,
  })
  const signedIn = Boolean(account.data?.account) || account.data?.requiresOpenaiAuth === false
  const installRuntime = useMutation({
    mutationFn: () => api('/api/v1/execution-profiles/codex-managed/runtime/install', { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['codex-managed-runtime'] }),
  })
  const login = useMutation({
    mutationFn: () => api<{ authUrl?: string }>('/api/v1/execution-profiles/codex-managed/login', {
      method: 'POST',
      body: jsonBody({ login_type: 'chatgpt' }),
    }),
    onSuccess: (result) => {
      if (result.authUrl) window.open(result.authUrl, '_blank', 'noopener,noreferrer')
    },
  })
  const save = useMutation({
    mutationFn: async () => {
      if (aiChoice === 'oauth') {
        await api('/api/v1/model-providers/openai-codex-oauth', {
          method: 'PATCH',
          body: jsonBody({ role: 'primary' }),
        })
      } else if (aiChoice === 'api') {
        await api('/api/v1/model-providers', {
          method: 'POST',
          body: jsonBody({
            provider_id: `api-${crypto.randomUUID().slice(0, 8)}`,
            display_name: apiName,
            provider_kind: 'openai_compatible',
            base_url: baseUrl,
            model_id: modelId,
            auth_mode: 'api_key',
            api_key: apiKey,
            role: 'primary',
            config: {},
          }),
        })
      }
      return api('/api/v1/profile', {
        method: 'PUT',
        body: jsonBody({
          complete_onboarding: true,
          updates: {
            exam: { type: 'academic', test_date: testDate || null },
            target,
            minimum_required: minimum,
            current,
            privacy,
          },
        }),
      })
    },
    onSuccess: async () => {
      window.history.replaceState(null, '', next === 'diagnostic' ? '/diagnostic' : '/today')
      await queryClient.invalidateQueries({ queryKey: ['bootstrap'] })
    },
  })
  const aiReady = aiChoice === 'later'
    || (aiChoice === 'oauth' && signedIn)
    || (aiChoice === 'api' && Boolean(baseUrl && modelId && apiKey))
  return <div className="standalone-onboarding">
    <div className="page page-narrow">
      <PageHeader eyebrow="First setup" title="建立你的 IELTS Academic 学习档案" description="这些信息只保存在本地，用于目标差距、训练分配和摸底状态判断；以后可在设置中修改。" />
      <section className="settings-section onboarding-step">
        <p className="eyebrow">1 · Exam</p><h2>考试与目标</h2>
        <label className="consent"><input type="checkbox" checked={academicConfirmed} onChange={(event) => setAcademicConfirmed(event.target.checked)} />我确认准备的是 IELTS Academic；当前系统不把 General Training 题目混入训练。</label>
        <label>考试日期（可留空）<input type="date" value={testDate} onChange={(event) => setTestDate(event.target.value)} /></label>
        <ScoreGrid title="目标分" values={target} onChange={setTarget} includeOverall />
        <ScoreGrid title="最低单项要求" values={minimum} onChange={setMinimum} includeOverall />
      </section>
      <section className="settings-section onboarding-step">
        <p className="eyebrow">2 · Baseline</p><h2>当前基线（可跳过）</h2>
        <p>如果没有可靠成绩，请保持“未知”。不要凭感觉填写 Band；稍后可在摸底页附加真实 Session。</p>
        <ScoreGrid title="已有成绩或可靠估分" values={current} onChange={setCurrent} allowUnknown />
      </section>
      <section className="settings-section onboarding-step">
        <p className="eyebrow">3 · Privacy</p><h2>隐私偏好</h2>
        <div className="import-boundary"><ShieldCheck /><p>这些偏好不会替代每次远程处理前的一次性确认。</p></div>
        <Toggle checked={privacy.allow_private_corpus} onChange={(value) => setPrivacy((currentValue) => ({ ...currentValue, allow_private_corpus: value }))}>允许在本机登记私人题库</Toggle>
        <Toggle checked={privacy.allow_cloud_upload} onChange={(value) => setPrivacy((currentValue) => ({ ...currentValue, allow_cloud_upload: value }))}>默认允许云端上传（仍需单次确认）</Toggle>
        <Toggle checked={privacy.store_raw_voice_audio} onChange={(value) => setPrivacy((currentValue) => ({ ...currentValue, store_raw_voice_audio: value }))}>允许保存原始口语音频</Toggle>
      </section>
      <section className="settings-section onboarding-step">
        <p className="eyebrow">4 · AI service</p><h2>选择智能反馈服务</h2>
        <p>模型只负责需要推理的步骤；题库、计时、Session、进度和保存都在本地完成。</p>
        <div className="onboarding-ai-choices">
          <label className={aiChoice === 'oauth' ? 'selected' : ''}>
            <input type="radio" name="ai-choice" checked={aiChoice === 'oauth'} onChange={() => setAiChoice('oauth')} />
            <Bot size={20} /><span><strong>使用 ChatGPT 登录</strong><small>推荐 · 无需 API Key</small></span>
          </label>
          <label className={aiChoice === 'api' ? 'selected' : ''}>
            <input type="radio" name="ai-choice" checked={aiChoice === 'api'} onChange={() => setAiChoice('api')} />
            <KeyRound size={20} /><span><strong>使用自己的 API</strong><small>DeepSeek、Qwen、GLM 等</small></span>
          </label>
          <label className={aiChoice === 'later' ? 'selected' : ''}>
            <input type="radio" name="ai-choice" checked={aiChoice === 'later'} onChange={() => setAiChoice('later')} />
            <ShieldCheck size={20} /><span><strong>暂不连接</strong><small>仍可做题和保存，稍后在设置中连接</small></span>
          </label>
        </div>
        {aiChoice === 'oauth' && (
          <div className="onboarding-ai-action">
            {!runtime.data?.installed ? (
              <button className="button secondary" onClick={() => installRuntime.mutate()} disabled={installRuntime.isPending || runtime.data?.npm_available === false}>
                {installRuntime.isPending ? <><RefreshCw className="spin" size={16} />正在安装</> : <><Download size={16} />安装登录组件</>}
              </button>
            ) : !signedIn ? (
              <button className="button secondary" onClick={() => login.mutate()} disabled={login.isPending}>
                <ExternalLink size={16} />打开 ChatGPT 登录
              </button>
            ) : <p className="inline-success"><CheckCircle2 size={16} />ChatGPT 已连接，可以继续。</p>}
          </div>
        )}
        {aiChoice === 'api' && (
          <div className="provider-form-grid onboarding-provider-form">
            <label>连接名称<input value={apiName} onChange={(event) => setApiName(event.target.value)} /></label>
            <label>Model ID<input value={modelId} onChange={(event) => setModelId(event.target.value)} /></label>
            <label className="wide-field">Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label>
            <label className="wide-field">API Key<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
          </div>
        )}
      </section>
      {save.isError && <ErrorState error={save.error} />}
      {(runtime.error || account.error || installRuntime.error || login.error) && <ErrorState error={runtime.error ?? account.error ?? installRuntime.error ?? login.error} />}
      <div className="onboarding-actions">
        <button className="button secondary" disabled={!academicConfirmed || !aiReady || save.isPending} onClick={() => { setNext('today'); save.mutate() }}>保存并进入首页</button>
        <button className="button primary" disabled={!academicConfirmed || !aiReady || save.isPending} onClick={() => { setNext('diagnostic'); save.mutate() }}><CheckCircle2 size={18} />保存并开始摸底</button>
      </div>
    </div>
  </div>
}

function ScoreGrid({ title, values, onChange, includeOverall = false, allowUnknown = false }: {
  title: string
  values: Record<string, number | null>
  onChange: (value: Record<string, number | null>) => void
  includeOverall?: boolean
  allowUnknown?: boolean
}) {
  const keys = includeOverall ? ['overall', ...modules] : [...modules]
  return <fieldset className="score-grid"><legend>{title}</legend>{keys.map((key) => <label key={key}>{label(key)}<select value={values[key] ?? ''} onChange={(event) => onChange({ ...values, [key]: event.target.value ? Number(event.target.value) : null })}>{allowUnknown && <option value="">未知</option>}{Array.from({ length: 15 }, (_, index) => 2 + index * 0.5).map((score) => <option key={score} value={score}>{score.toFixed(1)}</option>)}</select></label>)}</fieldset>
}

function Toggle({ checked, onChange, children }: { checked: boolean; onChange: (value: boolean) => void; children: string }) {
  return <label className="settings-toggle"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{children}</span></label>
}

function label(key: string) {
  return ({ overall: '总分', listening: '听力', reading: '阅读', writing: '写作', speaking: '口语' } as Record<string, string>)[key] ?? key
}
