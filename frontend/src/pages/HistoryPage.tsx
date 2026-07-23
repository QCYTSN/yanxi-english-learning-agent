import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type ProgressDashboard, type SessionSummary } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

export function HistoryPage() {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionSummary[]>('/api/v1/sessions?limit=100') })
  const allocation = useQuery({ queryKey: ['allocation'], queryFn: () => api<{ allocation: Record<string, number>; reasons: string[] }>('/api/v1/progress/allocation') })
  const dashboard = useQuery({ queryKey: ['progress-dashboard'], queryFn: () => api<ProgressDashboard>('/api/v1/progress/dashboard?days=90') })
  return (
    <div className="page">
      <PageHeader eyebrow="History" title="历史与下一步" description="正式 Session、错误和训练分配来自本地 Runtime，而不是 Agent 聊天记录。" />
      {allocation.data && (
        <section className="allocation-panel">
          <h2>当前 70/30 训练分配</h2>
          <div className="allocation-bars">
            {Object.entries(allocation.data.allocation).map(([module, value]) => (
              <div key={module}><span>{module}</span><div><i style={{ width: `${value * 100}%` }} /></div><strong>{Math.round(value * 100)}%</strong></div>
            ))}
          </div>
          <ul>{allocation.data.reasons.slice(0, 3).map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </section>
      )}
      {dashboard.isError && <ErrorState error={dashboard.error} />}
      {dashboard.data && (
        <>
          <section className="progress-module-grid" aria-label="四科进步概览">
            {Object.entries(dashboard.data.modules).map(([module, item]) => (
              <article className="metric-card" key={module}>
                <span>{module}</span>
                <strong>{item.average_band ?? '—'}</strong>
                <p>可进入趋势 {item.eligible_samples} · 训练观察 {item.observation_samples}</p>
                <small>{item.gap == null ? '尚无可信目标差距' : `距目标 ${item.gap.toFixed(2)}`}</small>
              </article>
            ))}
          </section>
          <section className="progress-detail-grid">
            <article className="panel">
              <h2>Writing / Speaking 分项</h2>
              {(['writing', 'speaking'] as const).map((module) => (
                <div key={module} className="criterion-group">
                  <h3>{module}</h3>
                  {dashboard.data.criteria[module].length ? dashboard.data.criteria[module].map((item) => (
                    <p key={item.criterion}><strong>{item.criterion}</strong><span>{item.average.toFixed(2)} · {item.samples} 个样本 · {item.evidence_class === 'progress_eligible' ? '可信趋势' : '训练观察'}</span></p>
                  )) : <p className="muted">暂无结构化分项证据。</p>}
                </div>
              ))}
            </article>
            <article className="panel">
              <h2>Reading 题型</h2>
              {dashboard.data.reading_question_types.length ? dashboard.data.reading_question_types.map((item) => (
                <p className="progress-row" key={item.question_type}><strong>{item.question_type}</strong><span>{Math.round(item.accuracy * 100)}% · {item.average_seconds == null ? '未记录耗时' : `${item.average_seconds}s`}</span></p>
              )) : <p className="muted">暂无已判分的题型记录。</p>}
            </article>
            <article className="panel">
              <h2>Listening 场景与错因</h2>
              {dashboard.data.listening.error_types.length ? dashboard.data.listening.error_types.map((item) => (
                <p className="progress-row" key={item.type}><strong>{item.type}</strong><span>{item.count} 次</span></p>
              )) : <p className="muted">暂无拼写、定位或干扰项错因记录。</p>}
            </article>
            <article className="panel">
              <h2>错误状态</h2>
              {Object.entries(dashboard.data.errors.counts).map(([status, count]) => (
                <p className="progress-row" key={status}><strong>{status}</strong><span>{count}</span></p>
              ))}
            </article>
          </section>
        </>
      )}
      {sessions.isPending && <LoadingState />}
      {sessions.isError && <ErrorState error={sessions.error} />}
      <div className="session-table table-scroll" tabIndex={0}>
        <table>
          <thead><tr><th>Session</th><th>科目</th><th>状态</th><th>估分</th><th>日期</th><th><span className="sr-only">操作</span></th></tr></thead>
          <tbody>{sessions.data?.map((session) => (
            <tr key={session.session_id}>
              <td>{session.session_id}</td><td>{session.module}</td><td><StatusBadge tone={session.status === 'completed' ? 'success' : 'neutral'}>{session.status}</StatusBadge></td><td>{session.band ?? '—'}</td><td>{formatDate(session.occurred_at)}</td><td>{sessionDestination(session) ? <Link to={sessionDestination(session)!}>查看</Link> : <span className="muted">已记录</span>}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}

function sessionDestination(session: SessionSummary) {
  if (session.module === 'speaking') return `/practice/speaking?session=${session.session_id}`
  if (session.module === 'listening') return `/practice/listening/${session.session_id}`
  if (!['writing', 'reading'].includes(session.module)) return null
  if (session.status === 'awaiting_revision' || session.status === 'completed') return `/feedback/${session.session_id}`
  return `/practice/${session.module}/${session.session_id}`
}

function formatDate(value?: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value))
}
