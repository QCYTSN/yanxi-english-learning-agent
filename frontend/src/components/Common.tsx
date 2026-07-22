import { AlertCircle, Check, LoaderCircle } from 'lucide-react'
import type { PropsWithChildren, ReactNode } from 'react'

export function PageHeader({ eyebrow, title, description, action }: {
  eyebrow?: string
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className="page-description">{description}</p>}
      </div>
      {action && <div className="page-action">{action}</div>}
    </header>
  )
}

export function LoadingState({ label = '正在读取本地数据' }: { label?: string }) {
  return <div className="state-card" role="status"><LoaderCircle className="spin" aria-hidden="true" />{label}</div>
}

export function ErrorState({ error, action }: { error: unknown; action?: ReactNode }) {
  const message = error instanceof Error ? error.message : '操作失败，请重试。'
  return (
    <div className="state-card error" role="alert">
      <AlertCircle aria-hidden="true" />
      <div><strong>暂时无法完成</strong><p>{message}</p>{action}</div>
    </div>
  )
}

export function EmptyState({ title, children, action }: PropsWithChildren<{ title: string; action?: ReactNode }>) {
  return <div className="empty-state"><h2>{title}</h2><p>{children}</p>{action}</div>
}

export function SaveState({ state }: { state: 'idle' | 'saving' | 'saved' | 'error' }) {
  const labels = { idle: '尚未保存', saving: '正在保存', saved: '已保存到本地', error: '保存失败' }
  return (
    <span className={`save-state ${state}`} aria-live="polite" role="status">
      {state === 'saving' ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />}
      {labels[state]}
    </span>
  )
}

export function StatusBadge({ children, tone = 'neutral' }: PropsWithChildren<{ tone?: 'neutral' | 'success' | 'warning' }>) {
  return <span className={`status-badge ${tone}`}>{children}</span>
}

export function PhaseRail({ active, phases }: { active: string; phases: string[] }) {
  return (
    <ol className="phase-rail" aria-label="学习阶段">
      {phases.map((phase) => <li key={phase} className={phase === active ? 'active' : undefined}>{phase}</li>)}
    </ol>
  )
}

export function StructuredDataTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (!entries.length) return null
  const longest = Math.max(...entries.map(([, value]) => Array.isArray(value) ? value.length : 1))
  return (
    <div className="table-scroll" tabIndex={0} aria-label="Task 1 数据表">
      <table>
        <thead><tr><th>类别</th>{Array.from({ length: longest }, (_, index) => <th key={index}>值 {index + 1}</th>)}</tr></thead>
        <tbody>
          {entries.map(([key, value]) => {
            const values = Array.isArray(value) ? value : [value]
            return <tr key={key}><th>{key}</th>{Array.from({ length: longest }, (_, index) => <td key={index}>{String(values[index] ?? '—')}</td>)}</tr>
          })}
        </tbody>
      </table>
    </div>
  )
}
