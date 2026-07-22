import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, type SessionSummary } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

export function HistoryPage() {
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: () => api<SessionSummary[]>('/api/v1/sessions?limit=100') })
  const allocation = useQuery({ queryKey: ['allocation'], queryFn: () => api<{ allocation: Record<string, number>; reasons: string[] }>('/api/v1/progress/allocation') })
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
  if (!['writing', 'reading'].includes(session.module)) return null
  if (session.status === 'awaiting_revision' || session.status === 'completed') return `/feedback/${session.session_id}`
  return `/practice/${session.module}/${session.session_id}`
}

function formatDate(value?: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value))
}
