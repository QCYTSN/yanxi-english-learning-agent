import { ArrowRight, RotateCcw } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { Bootstrap } from '../api/client'
import { PageHeader, StatusBadge } from '../components/Common'

export function TodayPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const active = bootstrap.active_session
  const activeWorkspace = active && ['writing', 'reading'].includes(active.module)
    ? `/practice/${active.module}/${active.session_id}`
    : null
  const target = bootstrap.profile?.target
  return (
    <div className="page page-narrow">
      <PageHeader
        eyebrow="Today"
        title="今天只推进一件重要的事"
        description="继续未完成练习优先；没有进行中的任务时，再选择新的训练。"
      />
      {active && (
        <section className="primary-card">
          <div>
            <StatusBadge tone="warning">进行中</StatusBadge>
            <h2>继续 {moduleLabel(active.module)} 练习</h2>
            <p>{active.session_id} · 当前状态 {statusLabel(active.status)}</p>
          </div>
          {activeWorkspace ? (
            <Link className="button primary" to={activeWorkspace}>
              <RotateCcw size={18} aria-hidden="true" />继续练习
            </Link>
          ) : (
            <Link className="button secondary" to="/history">查看记录</Link>
          )}
        </section>
      )}
      <section className="focus-section">
        <div className="section-heading">
          <div><p className="eyebrow">下一步</p><h2>{active ? '完成当前练习后再开始新任务' : '选择一次正式练习'}</h2></div>
        </div>
        <div className="choice-grid">
          <Link className="choice-card" to="/practice?module=writing">
            <span className="choice-number">W</span><div><h3>Writing</h3><p>独立完成、证据反馈、主动修改</p></div><ArrowRight aria-hidden="true" />
          </Link>
          <Link className="choice-card" to="/practice?module=reading">
            <span className="choice-number">R</span><div><h3>Reading</h3><p>严格计时或逐级提示练习</p></div><ArrowRight aria-hidden="true" />
          </Link>
        </div>
      </section>
      {target && (
        <section className="target-strip" aria-label="目标分数">
          <span>目标总分 <strong>{target.overall}</strong></span>
          <span>写作 <strong>{target.writing}</strong></span>
          <span>阅读 <strong>{target.reading}</strong></span>
          <span>数据版本 <strong>v{bootstrap.core_version}</strong></span>
        </section>
      )}
    </div>
  )
}

function moduleLabel(module: string) {
  return ({ writing: '写作', reading: '阅读', speaking: '口语', listening: '听力' } as Record<string, string>)[module] ?? module
}

function statusLabel(status: string) {
  return ({ draft: '准备开始', learner_working: '作答中', awaiting_feedback: '等待反馈', awaiting_revision: '等待修改' } as Record<string, string>)[status] ?? status
}
