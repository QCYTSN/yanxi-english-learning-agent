import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, ClipboardPlus, XCircle } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import { api, jsonBody, type SessionSummary } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type Diagnostic = {
  diagnostic_id?: string
  mode?: 'quick' | 'full'
  status: 'not_started' | 'active' | 'completed' | 'cancelled'
  started_at?: string
  completed_at?: string | null
  session_ids?: string[]
  coverage?: string[]
  missing_requirements?: string[]
  plan?: { purpose: string; requirements: Record<string, string> }
  result?: { baseline_scores?: Record<string, number>; baseline_status?: string; note?: string }
}

export function DiagnosticPage() {
  const [searchParams] = useSearchParams()
  const practiceUnitId = searchParams.get('practice_unit_id')
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'quick' | 'full'>('quick')
  const [sessionId, setSessionId] = useState('')
  const diagnostic = useQuery({ queryKey: ['diagnostic'], queryFn: () => api<Diagnostic>('/api/v1/diagnostics/current') })
  const sessions = useQuery({ queryKey: ['diagnostic-sessions'], queryFn: () => api<SessionSummary[]>('/api/v1/sessions?limit=200') })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['diagnostic'] })
  const start = useMutation({ mutationFn: () => api<Diagnostic>('/api/v1/diagnostics', { method: 'POST', body: jsonBody({ mode, practice_unit_id: practiceUnitId }) }), onSuccess: refresh })
  const attach = useMutation({
    mutationFn: () => api<Diagnostic>(`/api/v1/diagnostics/${diagnostic.data?.diagnostic_id}/sessions`, { method: 'POST', body: jsonBody({ session_id: sessionId }) }),
    onSuccess: () => { setSessionId(''); void refresh() },
  })
  const complete = useMutation({ mutationFn: () => api<Diagnostic>(`/api/v1/diagnostics/${diagnostic.data?.diagnostic_id}/complete`, { method: 'POST' }), onSuccess: async () => { await refresh(); await queryClient.invalidateQueries({ queryKey: ['bootstrap'] }) } })
  const cancel = useMutation({ mutationFn: () => api<Diagnostic>(`/api/v1/diagnostics/${diagnostic.data?.diagnostic_id}/cancel`, { method: 'POST' }), onSuccess: refresh })
  const error = start.error ?? attach.error ?? complete.error ?? cancel.error
  if (diagnostic.isPending) return <LoadingState />
  if (diagnostic.isError) return <ErrorState error={diagnostic.error} />
  const run = diagnostic.data
  const completedSessions = sessions.data?.filter((item) => item.status === 'completed' && !run.session_ids?.includes(item.session_id)) ?? []
  return <div className="page page-narrow">
    <PageHeader eyebrow="Diagnostic" title="四科摸底" description="摸底只整合真实 Session 证据。覆盖某一科不等于获得官方 Band；证据不足会明确保留为未知。" />
    {error && <ErrorState error={error} />}
    {run.status === 'not_started' || run.status === 'cancelled' ? <section className="settings-section">
      <h2>选择摸底强度</h2>
      <div className="diagnostic-mode-grid">
        <button className={mode === 'quick' ? 'active' : ''} onClick={() => setMode('quick')}><strong>Quick</strong><span>一篇阅读、Task 2、三部分口语，以及一份可靠听力结果</span></button>
        <button className={mode === 'full' ? 'active' : ''} onClick={() => setMode('full')}><strong>Full</strong><span>四科正式长度证据，包括 Writing Task 1 + Task 2</span></button>
      </div>
      <button className="button primary" disabled={start.isPending} onClick={() => start.mutate()}>建立摸底记录</button>
    </section> : null}
    {run.status === 'active' && <ActiveDiagnostic run={run} completedSessions={completedSessions} sessionId={sessionId} setSessionId={setSessionId} attach={() => attach.mutate()} complete={() => complete.mutate()} cancel={() => cancel.mutate()} busy={attach.isPending || complete.isPending || cancel.isPending} />}
    {run.status === 'completed' && <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">{run.mode}</p><h2>摸底已完成</h2></div><StatusBadge tone="success">证据已保存</StatusBadge></div>
      <div className="baseline-grid">{Object.entries(run.result?.baseline_scores ?? {}).map(([module, score]) => <div key={module}><span>{moduleLabel(module)}</span><strong>{score.toFixed(1)}</strong></div>)}</div>
      <p>{run.result?.note}</p><Link className="button primary" to="/today">返回今日学习</Link>
    </section>}
  </div>
}

function ActiveDiagnostic({ run, completedSessions, sessionId, setSessionId, attach, complete, cancel, busy }: {
  run: Diagnostic
  completedSessions: SessionSummary[]
  sessionId: string
  setSessionId: (value: string) => void
  attach: () => void
  complete: () => void
  cancel: () => void
  busy: boolean
}) {
  return <>
    <section className="settings-section">
      <div className="section-heading"><div><p className="eyebrow">{run.mode} · {run.diagnostic_id}</p><h2>证据覆盖</h2></div><StatusBadge tone="warning">进行中</StatusBadge></div>
      <div className="diagnostic-requirements">{Object.entries(run.plan?.requirements ?? {}).map(([key, text]) => <article key={key} className={(run.missing_requirements ?? []).some((item) => item.includes(key.replace('writing_', 'writing_'))) ? 'missing' : ''}><strong>{requirementLabel(key)}</strong><p>{text}</p></article>)}</div>
      <p><strong>已覆盖：</strong>{run.coverage?.length ? run.coverage.map(moduleLabel).join('、') : '尚无'}</p>
      <p><strong>仍缺证据：</strong>{run.missing_requirements?.length ? run.missing_requirements.map(requirementLabel).join('、') : '已满足完成条件'}</p>
      <div className="practice-shortcuts"><Link to="/practice?module=listening">去做听力</Link><Link to="/practice?module=reading">去做阅读</Link><Link to="/practice?module=writing">去做写作</Link><Link to="/practice?module=speaking">去做口语</Link></div>
    </section>
    <section className="settings-section">
      <h2>附加已完成的 Session</h2>
      <p>可以先去四科工作区完成练习，再回到这里选择对应记录。</p>
      <div className="diagnostic-attach"><select value={sessionId} onChange={(event) => setSessionId(event.target.value)}><option value="">选择已完成记录</option>{completedSessions.map((session) => <option key={session.session_id} value={session.session_id}>{moduleLabel(session.module)} · {session.session_id}{session.band ? ` · ${session.band}` : ''}</option>)}</select><button className="button secondary" disabled={!sessionId || busy} onClick={attach}><ClipboardPlus size={17} />附加</button></div>
      <div className="review-actions"><button className="button primary" disabled={Boolean(run.missing_requirements?.length) || busy} onClick={complete}><CheckCircle2 size={17} />完成摸底并更新基线</button><button className="button ghost" disabled={busy} onClick={cancel}><XCircle size={17} />取消本次摸底</button></div>
    </section>
  </>
}

function moduleLabel(value: string) {
  return ({ listening: '听力', reading: '阅读', writing: '写作', speaking: '口语' } as Record<string, string>)[value] ?? value
}

function requirementLabel(value: string) {
  return ({
    listening: '听力', reading: '阅读', writing_task1: '写作 Task 1', writing_task2: '写作 Task 2', speaking: '口语',
    listening_verified_result: '听力可靠结果', reading_timed_passage: '阅读计时篇章', reading_full_timed_test: '阅读完整模考',
    speaking_three_part_mock: '口语三部分模考',
  } as Record<string, string>)[value] ?? value
}
