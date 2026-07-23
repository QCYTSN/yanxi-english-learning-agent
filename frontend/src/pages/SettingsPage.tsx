import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Archive, CheckCircle2, RotateCcw, Save, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { api, jsonBody, type Bootstrap } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type BackupSummary = { backup_id: string; kind: string; created_at: string | null; schema_version?: string | null; file_count: number; size_bytes: number; status: string; error?: string }
type Health = { status: 'ok' | 'degraded' | 'failed'; checks: Record<string, unknown>; errors: string[]; warnings: string[] }
type Rubric = { rubric_id: string; module: string; publisher: string; standard: string; version?: string | null; source_reference: string; availability: string }
type Telemetry = { module: string; events: number; input_tokens: number; output_tokens: number; average_latency_ms?: number | null; tool_calls: number }

export function SettingsPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const queryClient = useQueryClient()
  const backups = useQuery({ queryKey: ['backups'], queryFn: () => api<BackupSummary[]>('/api/v1/backups') })
  const health = useQuery({ queryKey: ['system-health'], queryFn: () => api<Health>('/api/v1/system/health') })
  const rubrics = useQuery({ queryKey: ['rubrics'], queryFn: () => api<Rubric[]>('/api/v1/rubrics') })
  const telemetry = useQuery({ queryKey: ['telemetry'], queryFn: () => api<Telemetry[]>('/api/v1/telemetry/summary?days=30') })
  const create = useMutation({ mutationFn: () => api<BackupSummary>('/api/v1/backups', { method: 'POST' }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }) })
  const verify = useMutation({ mutationFn: (backupId: string) => api(`/api/v1/backups/${backupId}/verify`, { method: 'POST' }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['backups'] }) })
  const restore = useMutation({
    mutationFn: (backupId: string) => api(`/api/v1/backups/${backupId}/restore`, { method: 'POST', body: jsonBody({ confirmed: true }) }),
    onSuccess: async () => {
      window.alert('恢复完成，跨存储健康检查已通过。')
      await queryClient.invalidateQueries()
    },
  })
  function confirmRestore(backupId: string) {
    if (window.confirm(`恢复 ${backupId} 会替换当前学习数据。系统会先自动创建安全备份并在恢复后运行健康检查。是否继续？`)) restore.mutate(backupId)
  }
  return <div className="page page-narrow">
    <PageHeader eyebrow="Settings" title="设置与可信运行状态" description="管理本地 Profile，并检查 Agent、Rubric、Storage、Telemetry 和数据健康状态。" />
    <ProfileSection bootstrap={bootstrap} />
    <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">Doctor</p><h2>系统健康</h2></div>{health.data && <StatusBadge tone={health.data.status === 'ok' ? 'success' : 'warning'}>{health.data.status}</StatusBadge>}</div>
      {health.isPending && <LoadingState label="正在执行只读健康检查" />}{health.error && <ErrorState error={health.error} />}
      {health.data && <><dl className="definition-list"><div><dt>Core 版本</dt><dd>{bootstrap.core_version}</dd></div><div><dt>数据目录</dt><dd><code>{bootstrap.storage.data_home}</code></dd></div><div><dt>数据库</dt><dd>{String(health.data.checks.database_integrity ?? 'unknown')}</dd></div><div><dt>Schema</dt><dd>v{String(health.data.checks.schema_version ?? 'unknown')}</dd></div></dl>{health.data.errors.map((item) => <p className="import-error" key={item}>{item}</p>)}{health.data.warnings.map((item) => <p className="muted" key={item}>提醒：{item}</p>)}</>}
    </section>
    <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">Recovery</p><h2>本地备份与恢复</h2></div><button className="button primary" onClick={() => create.mutate()} disabled={create.isPending}><Archive size={17} />创建备份</button></div>
      <p>包含配置、数据库、Session、Corpus、Story Bank、报告、校准和注册媒体；恢复到不同目录时会自动重建本地媒体路径。</p>
      {(create.isError || verify.isError || restore.isError) && <ErrorState error={create.error ?? verify.error ?? restore.error} />}
      {backups.isPending && <LoadingState label="正在读取备份" />}{backups.isError && <ErrorState error={backups.error} />}
      <div className="adapter-list">{backups.data?.map((backup) => <article key={backup.backup_id}><div><h3>{backup.backup_id}</h3><p>{backup.kind} · {formatBytes(backup.size_bytes)} · {backup.file_count} 个文件{backup.created_at ? ` · ${new Date(backup.created_at).toLocaleString('zh-CN')}` : ''}</p>{backup.error && <p>{backup.error}</p>}</div><div className="row-actions"><StatusBadge tone={backup.status === 'available' ? 'success' : 'warning'}>{backup.status === 'available' ? '可用' : '无效'}</StatusBadge>{backup.status === 'available' && <><button className="button secondary" onClick={() => verify.mutate(backup.backup_id)} disabled={verify.isPending}><CheckCircle2 size={16} />校验</button><button className="button secondary" onClick={() => confirmRestore(backup.backup_id)} disabled={restore.isPending}><RotateCcw size={16} />恢复</button></>}</div></article>)}</div>
      {backups.data?.length === 0 && <p className="muted">还没有本地备份。</p>}
    </section>
    <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">Agent identity</p><h2>可用方式与身份边界</h2></div><StatusBadge tone="warning">未连接可调用 Process Agent</StatusBadge></div>
      <p>桌面快捷方式只启动本地 Runtime 和 UI，不会猜测或静默启动 Claude、OpenCode、Codex。</p>
      <div className="adapter-list">{bootstrap.agents.map((agent) => <article key={agent.id}><div><h3>{agent.label}</h3><p>{agent.identity.launcher_kind} · Provider {agent.identity.agent_provider ?? '未知'} · Model {agent.identity.model_display_name ?? agent.identity.model_id ?? '未知'}</p></div><StatusBadge tone={agent.available ? 'success' : 'warning'}>{agent.available ? '可用' : '不可用'}</StatusBadge></article>)}</div>
    </section>
    <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">Rubrics</p><h2>评分标准来源</h2></div><ShieldCheck /></div>
      {rubrics.isPending && <LoadingState />}{rubrics.error && <ErrorState error={rubrics.error} />}
      <div className="adapter-list">{rubrics.data?.map((rubric) => <article key={rubric.rubric_id}><div><h3>{rubric.standard}</h3><p>{rubric.publisher} · {rubric.module} · {rubric.version ?? '版本未注明'}</p><a href={rubric.source_reference} target="_blank" rel="noreferrer">查看来源</a></div><StatusBadge tone="success">{rubric.availability}</StatusBadge></article>)}</div>
    </section>
    <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">Telemetry · 30 days</p><h2>本地元数据统计</h2></div><Activity /></div>
      <p>只统计事件、Token 数、延迟和工具调用，不保存原始作文或提示词。</p>
      {telemetry.isPending && <LoadingState />}{telemetry.error && <ErrorState error={telemetry.error} />}
      {!telemetry.data?.length && <p className="muted">最近没有 Telemetry 记录。</p>}
      <div className="baseline-grid">{telemetry.data?.map((row) => <div key={row.module}><span>{row.module} · {row.events} events</span><strong>{row.input_tokens + row.output_tokens}</strong><small>tokens · avg {row.average_latency_ms ?? 0} ms</small></div>)}</div>
    </section>
  </div>
}

function ProfileSection({ bootstrap }: { bootstrap: Bootstrap }) {
  const queryClient = useQueryClient()
  const [testDate, setTestDate] = useState(bootstrap.profile?.test_date ?? '')
  const [targets, setTargets] = useState({ ...(bootstrap.profile?.target ?? {}) })
  const [minimum, setMinimum] = useState({ ...(bootstrap.profile?.minimum_required ?? {}) })
  const [privacy, setPrivacy] = useState({ ...(bootstrap.profile?.privacy ?? {}) })
  const save = useMutation({
    mutationFn: () => api('/api/v1/profile', { method: 'PUT', body: jsonBody({ updates: { exam: { type: 'academic', test_date: testDate || null }, target: targets, minimum_required: minimum, privacy }, complete_onboarding: false }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['bootstrap'] }),
  })
  return <section className="settings-section">
    <div className="section-heading"><div><p className="eyebrow">Profile</p><h2>考试、目标与隐私</h2></div><button className="button primary" disabled={save.isPending} onClick={() => save.mutate()}><Save size={17} />保存</button></div>
    <div className="handoff-options"><label>考试类型<input value="IELTS Academic" disabled /></label><label>考试日期<input type="date" value={testDate} onChange={(event) => setTestDate(event.target.value)} /></label></div>
    <CompactScores title="目标分" values={targets} setValues={setTargets} />
    <CompactScores title="最低要求" values={minimum} setValues={setMinimum} />
    <label className="settings-toggle"><input type="checkbox" checked={Boolean(privacy.allow_private_corpus)} onChange={(event) => setPrivacy((value) => ({ ...value, allow_private_corpus: event.target.checked }))} />允许在本机登记私人题库</label>
    <label className="settings-toggle"><input type="checkbox" checked={Boolean(privacy.allow_cloud_upload)} onChange={(event) => setPrivacy((value) => ({ ...value, allow_cloud_upload: event.target.checked }))} />默认允许云端上传（每次仍需确认）</label>
    <label className="settings-toggle"><input type="checkbox" checked={Boolean(privacy.store_raw_voice_audio)} onChange={(event) => setPrivacy((value) => ({ ...value, store_raw_voice_audio: event.target.checked }))} />保存原始口语音频</label>
    {save.isError && <ErrorState error={save.error} />}
  </section>
}

function CompactScores({ title, values, setValues }: { title: string; values: Record<string, number>; setValues: (value: Record<string, number>) => void }) {
  return <fieldset className="score-grid compact"><legend>{title}</legend>{Object.entries(values).map(([key, value]) => <label key={key}>{key}<select value={value} onChange={(event) => setValues({ ...values, [key]: Number(event.target.value) })}>{Array.from({ length: 15 }, (_, index) => 2 + index * 0.5).map((score) => <option key={score} value={score}>{score.toFixed(1)}</option>)}</select></label>)}</fieldset>
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}
