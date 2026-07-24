import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, RotateCcw } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { api, jsonBody, type Bootstrap, type PracticeUnit, type StudyContext, type TodayPlanTask } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

export function TodayPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const navigate = useNavigate()
  const active = bootstrap.active_session
  const activeWorkspace = active ? sessionDestination(active) : null
  const target = bootstrap.profile?.target
  const context = useQuery({
    queryKey: ['today-context'],
    queryFn: () => api<StudyContext>('/api/v1/today'),
    enabled: !bootstrap.setup_required,
  })
  const materialise = useMutation({
    mutationFn: (slot: 'primary' | 'consolidation' | 'diagnostic') => api<PracticeUnit>('/api/v1/today/materialise', {
      method: 'POST',
      body: jsonBody({ slot }),
    }),
    onSuccess: (unit) => navigate(unit.launch_url),
  })
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
      {context.isPending && <LoadingState />}
      {context.isError && <ErrorState error={context.error} />}
      {materialise.isError && <ErrorState error={materialise.error} />}
      {context.data?.today_plan && !active && (
        <section className="today-plan" aria-labelledby="today-plan-heading">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Runtime recommendation</p>
              <h2 id="today-plan-heading">今日 70/30 学习安排</h2>
            </div>
            <span className="muted">正式模考可用：{context.data.today_plan.verified_full_mock_count} 套</span>
          </div>
          <div className="today-task-grid">
            <TodayTask task={context.data.today_plan.primary} label="70% 弱项主任务" primary slot="primary" start={(slot) => materialise.mutate(slot)} pending={materialise.isPending} />
            <TodayTask task={context.data.today_plan.consolidation} label="30% 巩固任务" slot="consolidation" start={(slot) => materialise.mutate(slot)} pending={materialise.isPending} />
          </div>
        </section>
      )}
      {context.data?.review_queue && (
        <section className="settings-section">
          <div className="section-heading">
            <div><p className="eyebrow">Review Queue</p><h2>统一待复习队列</h2></div>
            <Link to="/history">查看全部 {context.data.review_queue.counts.pending ?? 0} 项</Link>
          </div>
          {context.data.review_queue.items.length === 0 ? <p className="muted">当前没有到期复习任务。</p> : (
            <div className="adapter-list">{context.data.review_queue.items.map((task) => (
              <article key={task.review_task_id}>
                <div><h3>{task.title}</h3><p>{task.action}</p></div>
                <StatusBadge tone={task.priority >= 80 ? 'warning' : 'neutral'}>{moduleLabel(task.module)}</StatusBadge>
              </article>
            ))}</div>
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
          <Link className="choice-card" to="/practice?module=speaking">
            <span className="choice-number">S</span><div><h3>Speaking</h3><p>生成 Voice / Live 任务包并导回报告</p></div><ArrowRight aria-hidden="true" />
          </Link>
          <Link className="choice-card" to="/practice?module=listening">
            <span className="choice-number">L</span><div><h3>Listening</h3><p>高频场景表达听写与间隔复习</p></div><ArrowRight aria-hidden="true" />
          </Link>
        </div>
      </section>
      <section className="diagnostic-callout">
        <div><p className="eyebrow">Baseline</p><h2>四科摸底：{bootstrap.onboarding?.baseline_status === 'complete' ? '基线已完整' : '仍有证据缺口'}</h2><p>用真实完成的 Session 建立当前基线；不确定的科目保持未知。</p></div>
        {bootstrap.onboarding?.baseline_status === 'complete'
          ? <Link className="button secondary" to="/diagnostic">查看摸底<ArrowRight size={17} /></Link>
          : <button className="button secondary" disabled={materialise.isPending} onClick={() => materialise.mutate('diagnostic')}>继续摸底<ArrowRight size={17} /></button>}
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

function TodayTask({ task, label, slot, start, pending, primary = false }: { task: TodayPlanTask; label: string; slot: 'primary' | 'consolidation'; start: (slot: 'primary' | 'consolidation') => void; pending: boolean; primary?: boolean }) {
  return (
    <article className={primary ? 'today-task-card primary-card' : 'today-task-card'}>
      <div>
        <div className="task-badges">
          <StatusBadge tone={task.content_available ? 'success' : 'warning'}>{task.content_available ? '内容可用' : '降级任务'}</StatusBadge>
          <span>{label}</span>
        </div>
        <h3>{task.title}</h3>
        <p>{task.reason}</p>
        <dl className="task-metrics">
          <div><dt>预计时间</dt><dd>{task.estimated_minutes} 分钟</dd></div>
          <div><dt>目标差距</dt><dd>{task.target_gap == null ? '证据不足' : `${task.target_gap.toFixed(2)} Band`}</dd></div>
          <div><dt>训练模式</dt><dd>{task.practice_mode}</dd></div>
        </dl>
      </div>
      <button className={primary ? 'button primary' : 'button secondary'} disabled={pending} onClick={() => start(slot)}>开始任务<ArrowRight size={17} /></button>
    </article>
  )
}

function sessionDestination(session: { module: string; session_id: string }) {
  if (session.module === 'speaking') return `/practice/speaking?session=${session.session_id}`
  if (session.module === 'listening') return `/practice/listening/${session.session_id}`
  if (session.module === 'writing' || session.module === 'reading') return `/practice/${session.module}/${session.session_id}`
  return null
}

function moduleLabel(module: string) {
  return ({ writing: '写作', reading: '阅读', speaking: '口语', listening: '听力' } as Record<string, string>)[module] ?? module
}

function statusLabel(status: string) {
  return ({ draft: '准备开始', learner_working: '作答中', awaiting_feedback: '等待反馈', awaiting_revision: '等待修改' } as Record<string, string>)[status] ?? status
}
