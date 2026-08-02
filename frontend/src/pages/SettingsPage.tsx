import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  Archive,
  ArrowLeft,
  BookOpenCheck,
  Bot,
  CheckCircle2,
  ChevronRight,
  Database,
  HardDrive,
  Laptop,
  Plus,
  RotateCcw,
  Save,
  ServerCog,
  ShieldCheck,
  UserRound,
} from 'lucide-react'
import { Link, Navigate, useParams, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import {
  api,
  jsonBody,
  type Bootstrap,
  type ExternalAgentProfile,
  type ModelProvider,
} from '../api/client'
import { ErrorState, LoadingState, StatusBadge } from '../components/Common'
import { ModelProvidersSection } from '../components/ModelProvidersSection'
import { normalisePerformance, type PerformanceResponse } from './settingsPerformance'

type BackupSummary = {
  backup_id: string
  kind: string
  created_at: string | null
  file_count: number
  size_bytes: number
  status: string
  error?: string
}
type Health = {
  status: 'ok' | 'degraded' | 'failed'
  checks: Record<string, unknown>
  errors: string[]
  warnings: string[]
}
type Rubric = {
  rubric_id: string
  module: string
  publisher: string
  standard: string
  version?: string | null
  source_reference: string
  availability: string
}

const settingsSections = [
  { id: 'profile', title: '学习档案', description: '考试目标、当前基线与隐私偏好', icon: UserRound },
  { id: 'models', title: '模型服务', description: '主模型、备用模型与自定义 API', icon: Bot },
  { id: 'data', title: '本地数据', description: 'SQLite、备份、恢复与数据位置', icon: Database },
  { id: 'trust', title: '教学标准', description: '评分标准来源与教学边界', icon: BookOpenCheck },
  { id: 'advanced', title: '高级', description: '本地模型、外部 Agent 与开发者选项', icon: ServerCog },
  { id: 'system', title: '系统状态', description: '健康检查、容量与运行性能', icon: Activity },
] as const

export function SettingsPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const { section: pathSection } = useParams()
  const [params] = useSearchParams()
  const legacySection = params.get('section')
  const section = pathSection ?? legacySection
  const active = settingsSections.find((item) => item.id === section)

  if (!pathSection && legacySection && active) {
    return <Navigate to={`/settings/${active.id}`} replace />
  }

  return (
    <div className="settings-page">
      <header className="settings-page-header">
        <div>
          {active && <Link className="settings-back" to="/settings"><ArrowLeft size={16} />设置</Link>}
          <h1>{active?.title ?? '设置'}</h1>
          <p>{active?.description ?? '模型、学习档案和本地数据都集中在这里；学习页面只保留学习。'}</p>
        </div>
      </header>
      {!active && <SettingsOverview bootstrap={bootstrap} />}
      {section === 'profile' && <ProfileSection bootstrap={bootstrap} />}
      {section === 'models' && <ModelProvidersSection />}
      {section === 'data' && <DataSection bootstrap={bootstrap} />}
      {section === 'trust' && <TrustSection />}
      {section === 'advanced' && <AdvancedSection />}
      {section === 'system' && <SystemSection bootstrap={bootstrap} />}
      {section && !active && <Navigate to="/settings" replace />}
    </div>
  )
}

function SettingsOverview({ bootstrap }: { bootstrap: Bootstrap }) {
  const primary = bootstrap.model_providers?.find((item) => item.role === 'primary')
  return (
    <>
      <section className="settings-status-strip" aria-label="系统摘要">
        <div><span className="status-dot ok" /><small>本地服务</small><strong>在线</strong></div>
        <div>
          <span className={`status-dot ${primary?.available ? 'ok' : 'warning'}`} />
          <small>主模型</small>
          <strong>{primary?.display_name ?? '未连接'}</strong>
        </div>
        <div><span className="status-dot ok" /><small>数据</small><strong>SQLite · 本机</strong></div>
      </section>
      <section className="settings-card-grid">
        {settingsSections.map(({ id, title, description, icon: Icon }) => (
          <Link key={id} className="settings-category-card" to={`/settings/${id}`}>
            <Icon size={21} strokeWidth={1.65} aria-hidden="true" />
            <div><h2>{title}</h2><p>{description}</p></div>
            <ChevronRight size={18} aria-hidden="true" />
          </Link>
        ))}
      </section>
    </>
  )
}

function ProfileSection({ bootstrap }: { bootstrap: Bootstrap }) {
  const queryClient = useQueryClient()
  const [testDate, setTestDate] = useState(bootstrap.profile?.test_date ?? '')
  const [targets, setTargets] = useState({ ...(bootstrap.profile?.target ?? {}) })
  const [minimum, setMinimum] = useState({ ...(bootstrap.profile?.minimum_required ?? {}) })
  const [privacy, setPrivacy] = useState({ ...(bootstrap.profile?.privacy ?? {}) })
  const save = useMutation({
    mutationFn: () => api('/api/v1/profile', {
      method: 'PUT',
      body: jsonBody({
        updates: {
          exam: { type: 'academic', test_date: testDate || null },
          target: targets,
          minimum_required: minimum,
          privacy,
        },
        complete_onboarding: false,
      }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bootstrap'] }),
  })
  return (
    <div className="settings-detail-stack">
      <section className="settings-panel">
        <div className="section-heading"><div><h2>考试与目标</h2><p>用于差距计算和 70/30 训练分配。</p></div></div>
        <div className="model-choice-row">
          <label>考试类型<input value="IELTS Academic" disabled /></label>
          <label>考试日期<input type="date" value={testDate} onChange={(event) => setTestDate(event.target.value)} /></label>
        </div>
        <CompactScores title="目标分" values={targets} setValues={setTargets} />
        <CompactScores title="最低要求" values={minimum} setValues={setMinimum} />
      </section>
      <section className="settings-panel">
        <div className="section-heading"><div><h2>隐私偏好</h2><p>远程处理仍会在需要时进行单次确认。</p></div><ShieldCheck size={20} /></div>
        <Toggle checked={Boolean(privacy.allow_private_corpus)} onChange={(value) => setPrivacy((current) => ({ ...current, allow_private_corpus: value }))}>允许在本机登记私人题库</Toggle>
        <Toggle checked={Boolean(privacy.allow_cloud_upload)} onChange={(value) => setPrivacy((current) => ({ ...current, allow_cloud_upload: value }))}>允许在确认后把必要材料发给主模型</Toggle>
        <Toggle checked={Boolean(privacy.store_raw_voice_audio)} onChange={(value) => setPrivacy((current) => ({ ...current, store_raw_voice_audio: value }))}>保存原始口语音频</Toggle>
      </section>
      <div className="settings-save-bar">
        <button className="button primary" disabled={save.isPending} onClick={() => save.mutate()}><Save size={16} />保存学习档案</button>
      </div>
      {save.error && <ErrorState error={save.error} />}
    </div>
  )
}

function DataSection({ bootstrap }: { bootstrap: Bootstrap }) {
  const queryClient = useQueryClient()
  const [showAllBackups, setShowAllBackups] = useState(false)
  const backups = useQuery({ queryKey: ['backups'], queryFn: () => api<BackupSummary[]>('/api/v1/backups') })
  const create = useMutation({
    mutationFn: () => api<BackupSummary>('/api/v1/backups', { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }),
  })
  const verify = useMutation({
    mutationFn: (backupId: string) => api(`/api/v1/backups/${backupId}/verify`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }),
  })
  const restore = useMutation({
    mutationFn: (backupId: string) => api(`/api/v1/backups/${backupId}/restore`, {
      method: 'POST',
      body: jsonBody({ confirmed: true }),
    }),
    onSuccess: () => queryClient.invalidateQueries(),
  })
  function confirmRestore(backupId: string) {
    if (window.confirm('恢复会替换当前学习数据；系统会先自动创建安全备份。是否继续？')) restore.mutate(backupId)
  }
  return (
    <div className="settings-detail-stack">
      <section className="settings-panel">
        <div className="section-heading"><div><h2>数据位置</h2><p>SQLite 是当前唯一数据真源，不依赖 Docker。</p></div><HardDrive size={20} /></div>
        <dl className="definition-list">
          <div><dt>数据目录</dt><dd><code>{bootstrap.storage.data_home}</code></dd></div>
          <div><dt>数据库</dt><dd><code>{bootstrap.storage.database_path}</code></dd></div>
          <div><dt>备份目录</dt><dd><code>{bootstrap.storage.backups_path}</code></dd></div>
        </dl>
      </section>
      <section className="settings-panel">
        <div className="section-heading">
          <div><h2>备份与恢复</h2><p>包含 Session、Corpus、报告、媒体注册和配置。</p></div>
          <button className="button primary" onClick={() => create.mutate()} disabled={create.isPending}><Archive size={16} />创建备份</button>
        </div>
        {backups.isPending && <LoadingState label="正在读取备份" />}
        <div className="simple-list backup-list">
          {backups.data?.slice(0, showAllBackups ? undefined : 6).map((backup) => (
            <article key={backup.backup_id}>
              <div><strong>{backup.backup_id}</strong><p>{backup.kind} · {formatBytes(backup.size_bytes)} · {backup.file_count} 个文件</p></div>
              <div className="row-actions">
                <StatusBadge tone={backup.status === 'available' ? 'success' : 'warning'}>{backup.status === 'available' ? '可用' : '无效'}</StatusBadge>
                {backup.status === 'available' && <>
                  <button className="button ghost" onClick={() => verify.mutate(backup.backup_id)}><CheckCircle2 size={15} />校验</button>
                  <button className="button ghost" onClick={() => confirmRestore(backup.backup_id)}><RotateCcw size={15} />恢复</button>
                </>}
              </div>
            </article>
          ))}
          {backups.data?.length === 0 && <p className="muted">还没有本地备份。</p>}
        </div>
        {(backups.data?.length ?? 0) > 6 && <button className="button ghost backup-list-toggle" type="button" onClick={() => setShowAllBackups((value) => !value)}>{showAllBackups ? '收起旧备份' : `查看全部 ${backups.data?.length ?? 0} 个备份`}</button>}
      </section>
      {(create.error || verify.error || restore.error || backups.error) && <ErrorState error={create.error ?? verify.error ?? restore.error ?? backups.error} />}
    </div>
  )
}

function TrustSection() {
  const rubrics = useQuery({ queryKey: ['rubrics'], queryFn: () => api<Rubric[]>('/api/v1/rubrics') })
  return (
    <div className="settings-detail-stack">
      <section className="settings-panel">
        <div className="section-heading"><div><h2>不可绕过的教学边界</h2><p>这些规则由 Runtime 和 Schema 共同执行，不由模型自由决定。</p></div><ShieldCheck size={20} /></div>
        <div className="trust-boundaries">
          <p><strong>Writing</strong><span>证据与估分优先，学习者修改第二，模型范文最后。</span></p>
          <p><strong>Reading</strong><span>逐级提示先于答案揭示，解释必须定位原文证据。</span></p>
          <p><strong>Speaking</strong><span>完整 Mock 中途不纠错；AI 分数必须显示置信度。</span></p>
          <p><strong>数据</strong><span>模型输出验证通过后，才能由 Runtime 原子保存。</span></p>
        </div>
      </section>
      <section className="settings-panel">
        <div className="section-heading"><div><h2>评分标准来源</h2><p>只使用系统登记并可追溯的 Rubric。</p></div></div>
        {rubrics.isPending && <LoadingState />}
        <div className="simple-list">{rubrics.data?.map((rubric) => (
          <article key={rubric.rubric_id}>
            <div><strong>{rubric.standard}</strong><p>{rubric.publisher} · {rubric.module} · {rubric.version ?? '版本未注明'}</p></div>
            <a href={rubric.source_reference} target="_blank" rel="noreferrer">查看来源</a>
          </article>
        ))}</div>
        {rubrics.error && <ErrorState error={rubrics.error} />}
      </section>
    </div>
  )
}

function AdvancedSection() {
  const queryClient = useQueryClient()
  const providers = useQuery({
    queryKey: ['model-providers'],
    queryFn: () => api<ModelProvider[]>('/api/v1/model-providers'),
  })
  const agents = useQuery({
    queryKey: ['external-agents'],
    queryFn: () => api<ExternalAgentProfile[]>('/api/v1/external-agents?diagnostics=true'),
  })
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:11434/v1')
  const [modelId, setModelId] = useState('')
  const createLocal = useMutation({
    mutationFn: () => api('/api/v1/model-providers', {
      method: 'POST',
      body: jsonBody({
        provider_id: `local-${crypto.randomUUID().slice(0, 8)}`,
        display_name: '本地模型',
        provider_kind: 'local_http',
        base_url: baseUrl,
        model_id: modelId,
        auth_mode: 'none',
        role: providers.data?.some((item) => item.role === 'primary') ? 'disabled' : 'primary',
        config: {},
      }),
    }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['model-providers'] })
      await queryClient.invalidateQueries({ queryKey: ['bootstrap'] })
    },
  })
  return (
    <div className="settings-detail-stack">
      <section className="settings-panel">
        <div className="section-heading"><div><h2>本地 HTTP 模型</h2><p>连接 Ollama、LM Studio 或其他 OpenAI-compatible 本地服务。</p></div><Laptop size={20} /></div>
        <div className="model-choice-row">
          <label>Base URL<input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} /></label>
          <label>Model ID<input value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="local-model" /></label>
          <button className="button secondary" onClick={() => createLocal.mutate()} disabled={!baseUrl || !modelId || createLocal.isPending}><Plus size={16} />添加本地模型</button>
        </div>
        {providers.data?.filter((item) => item.provider_kind === 'local_http').map((item) => <p className="muted" key={item.provider_id}>{item.display_name} · {item.model_id} · {item.base_url}</p>)}
        {createLocal.error && <ErrorState error={createLocal.error} />}
      </section>
      <section className="settings-panel">
        <div className="section-heading"><div><h2>外部 Agent</h2><p>只用于材料整理、格式转换和开发者流程，不能成为教学主模型。</p></div><Bot size={20} /></div>
        {agents.isPending && <LoadingState label="正在检查本地 Agent" />}
        <div className="simple-list">{agents.data?.map((agent) => (
          <article key={agent.agent_profile_id}>
            <div><strong>{agent.display_name}</strong><p>{purposeLabel(agent.purpose)} · {agent.identity.launcher_kind}</p></div>
            <StatusBadge tone={agent.available ? 'success' : 'neutral'}>{agent.available ? '可调用' : '未检测到'}</StatusBadge>
          </article>
        ))}</div>
        {agents.error && <ErrorState error={agents.error} />}
      </section>
    </div>
  )
}

function SystemSection({ bootstrap }: { bootstrap: Bootstrap }) {
  const health = useQuery({ queryKey: ['system-health'], queryFn: () => api<Health>('/api/v1/system/health') })
  const performance = useQuery({
    queryKey: ['system-performance'],
    queryFn: () => api<PerformanceResponse>('/api/v1/system/performance'),
    refetchInterval: 30_000,
  })
  const snapshot = normalisePerformance(performance.data)
  return (
    <div className="settings-detail-stack">
      <section className="settings-panel">
        <div className="section-heading"><div><h2>系统健康</h2><p>只读检查，不会修改学习数据。</p></div>{health.data && <StatusBadge tone={health.data.status === 'ok' ? 'success' : 'warning'}>{health.data.status}</StatusBadge>}</div>
        {health.isPending && <LoadingState />}
        {health.data && <dl className="definition-list">
          <div><dt>Core 版本</dt><dd>{bootstrap.core_version}</dd></div>
          <div><dt>数据库完整性</dt><dd>{String(health.data.checks?.database_integrity ?? 'unknown')}</dd></div>
          <div><dt>Schema</dt><dd>v{String(health.data.checks?.schema_version ?? 'unknown')}</dd></div>
        </dl>}
        {health.error && <ErrorState error={health.error} />}
      </section>
      <section className="settings-panel">
        <div className="section-heading"><div><h2>运行容量</h2><p>SQLite 使用 WAL；当前不需要 Docker 或额外数据库服务。</p></div><Activity size={20} /></div>
        {performance.isPending && <LoadingState />}
        {performance.data && <div className="system-metrics">
          <div><span>请求样本</span><strong>{snapshot.sampleCount}</strong></div>
          <div><span>中位延迟</span><strong>{snapshot.p50Ms} ms</strong></div>
          <div><span>p95 延迟</span><strong>{snapshot.p95Ms} ms</strong></div>
          <div><span>数据库</span><strong>{formatBytes(snapshot.databaseSizeBytes)}</strong></div>
        </div>}
        {performance.error && <ErrorState error={performance.error} />}
      </section>
    </div>
  )
}

function CompactScores({ title, values, setValues }: {
  title: string
  values: Record<string, number>
  setValues: (value: Record<string, number>) => void
}) {
  return <fieldset className="score-grid compact"><legend>{title}</legend>{Object.entries(values).map(([key, value]) => <label key={key}>{scoreLabel(key)}<select value={value} onChange={(event) => setValues({ ...values, [key]: Number(event.target.value) })}>{Array.from({ length: 15 }, (_, index) => 2 + index * 0.5).map((score) => <option key={score} value={score}>{score.toFixed(1)}</option>)}</select></label>)}</fieldset>
}

function Toggle({ checked, onChange, children }: {
  checked: boolean
  onChange: (value: boolean) => void
  children: string
}) {
  return <label className="settings-toggle"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{children}</span></label>
}

function scoreLabel(key: string) {
  return ({ overall: '总分', listening: '听力', reading: '阅读', writing: '写作', speaking: '口语' } as Record<string, string>)[key] ?? key
}

function purposeLabel(value: string) {
  return ({
    material_operations: '材料整理',
    format_conversion: '格式转换',
    corpus_maintenance: '题库维护',
    developer_tools: '开发者工具',
    manual_handoff: '手动交接',
  } as Record<string, string>)[value] ?? value
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
