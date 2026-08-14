import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CalendarDays, CheckCircle2, ListChecks, Play, TrendingDown, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  api,
  type LearningModelSnapshot,
  type PracticeUnit,
  type ProgressAction,
  type ProgressDashboard,
  type ProgressTrendSample,
  type ReviewTask,
  type SessionSummary,
  type WeeklyReport,
} from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'
import { dimensionLabel, LEARNING_DIMENSIONS, masteryPresentation, skillPresentation } from '../learningPresentation'
import { buildTrendGeometry } from './progressPresentation'

const MODULE_LABELS: Record<string, string> = {
  listening: '听力',
  reading: '阅读',
  writing: '写作',
  speaking: '口语',
}

export function HistoryPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [days, setDays] = useState(90)
  const [activeTab, setActiveTab] = useState<'trends' | 'reviews' | 'skills'>('trends')

  const sessions = useQuery({
    queryKey: ['sessions'],
    queryFn: () => api<SessionSummary[]>('/api/v1/sessions?limit=100'),
  })
  const dashboard = useQuery({
    queryKey: ['progress-dashboard', days],
    queryFn: () => api<ProgressDashboard>(`/api/v1/progress/dashboard?days=${days}`),
  })
  const weekly = useQuery({
    queryKey: ['progress-weekly'],
    queryFn: () => api<WeeklyReport>('/api/v1/progress/weekly'),
  })
  const weeklyHistory = useQuery({
    queryKey: ['progress-weekly-history'],
    queryFn: () => api<WeeklyReport[]>('/api/v1/progress/weekly/history?limit=8'),
    enabled: weekly.isSuccess,
  })
  const reviewTasks = useQuery({
    queryKey: ['review-tasks'],
    queryFn: () => api<ReviewTask[]>('/api/v1/review-tasks?status=pending&limit=100'),
  })
  const startAction = useMutation({
    mutationFn: (action: ProgressAction) =>
      api<PracticeUnit>(`/api/v1/progress/actions/${encodeURIComponent(action.action_id)}/start`, { method: 'POST' }),
    onSuccess: (unit) => navigate(unit.launch_url),
  })
  const startReview = useMutation({
    mutationFn: (reviewTaskId: string) =>
      api<PracticeUnit>(`/api/v1/review-tasks/${reviewTaskId}/start`, { method: 'POST' }),
    onSuccess: (unit) => navigate(unit.launch_url),
  })
  const completeReview = useMutation({
    mutationFn: (reviewTaskId: string) =>
      api<ReviewTask>(`/api/v1/review-tasks/${reviewTaskId}/complete`, { method: 'POST' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['review-tasks'] })
      queryClient.invalidateQueries({ queryKey: ['progress-dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['progress-weekly'] })
    },
  })

  const pendingReviewCount = reviewTasks.data?.length ?? 0
  const nextActionsCount = dashboard.data?.next_actions.length ?? 0

  return (
    <div className="page page-progress">
      <PageHeader
        eyebrow="学习档案"
        title="从学习证据决定下一步"
        description="只用符合证据规则的成绩判断趋势；训练观察保留可见，但不会冒充正式进步。"
      />

      {/* 顶部学情概貌卡片 */}
      <section className="progress-overview-hero" aria-label="学情概貌">
        <div className="overview-hero-scores">
          <span className="overview-label">四科当前表现</span>
          <div className="overview-score-pills">
            {Object.entries(dashboard.data?.modules ?? {}).map(([modKey, modData]) => (
              <span className="score-pill" key={modKey}>
                <small>{MODULE_LABELS[modKey] ?? modKey}</small>
                <strong>{modData.average_band ? modData.average_band.toFixed(1) : '—'}</strong>
              </span>
            ))}
          </div>
        </div>
        <div className="overview-hero-stats">
          <div>
            <small>待处理复习</small>
            <strong>{pendingReviewCount} 项</strong>
          </div>
          <div>
            <small>建议动作</small>
            <strong>{nextActionsCount} 项</strong>
          </div>
        </div>
      </section>

      {/* 三级分类选项卡 */}
      <nav className="progress-tab-nav" aria-label="进步档案分类">
        <button
          type="button"
          className={`progress-tab-btn${activeTab === 'trends' ? ' active' : ''}`}
          onClick={() => setActiveTab('trends')}
        >
          📈 成绩走势与行动
        </button>
        <button
          type="button"
          className={`progress-tab-btn${activeTab === 'reviews' ? ' active' : ''}`}
          onClick={() => setActiveTab('reviews')}
        >
          🎯 错题与复盘队列 {pendingReviewCount > 0 && <span className="tab-counter-badge">{pendingReviewCount}</span>}
        </button>
        <button
          type="button"
          className={`progress-tab-btn${activeTab === 'skills' ? ' active' : ''}`}
          onClick={() => setActiveTab('skills')}
        >
          📑 能力图谱与周报
        </button>
      </nav>

      {/* TAB 1: 成绩走势与下一步动作 */}
      {activeTab === 'trends' && (
        <section className="progress-tab-pane">
          <div className="progress-toolbar" aria-label="趋势时间范围">
            <span>趋势时间范围</span>
            {[30, 90, 180].map((value) => (
              <button
                className={days === value ? 'active' : ''}
                key={value}
                onClick={() => setDays(value)}
                type="button"
              >
                {value} 天
              </button>
            ))}
          </div>

          {dashboard.isPending && <LoadingState label="正在汇总本地学习证据" />}
          {dashboard.isError && <ErrorState error={dashboard.error} />}
          {dashboard.data && (
            <>
              <section className="progress-module-grid" aria-label="四科进步趋势">
                {Object.entries(dashboard.data.modules).map(([module, item]) => (
                  <article className="trend-card" key={module}>
                    <div className="trend-card-heading">
                      <div>
                        <span>{MODULE_LABELS[module] ?? module}</span>
                        <strong>{item.average_band?.toFixed(1) ?? '—'}</strong>
                      </div>
                      <TrendDirection
                        direction={item.trend_summary.direction}
                        delta={item.trend_summary.delta}
                      />
                    </div>
                    <TrendChart
                      samples={item.trend}
                      target={item.target}
                      label={`${MODULE_LABELS[module] ?? module} ${days} 天成绩趋势`}
                    />
                    <div className="trend-evidence">
                      <span>可信成绩 <strong>{item.eligible_samples}</strong></span>
                      <span>训练观察 <strong>{item.observation_samples}</strong></span>
                      <span>{item.gap == null ? '目标差距待建立' : `距目标 ${item.gap.toFixed(2)}`}</span>
                    </div>
                  </article>
                ))}
              </section>

              <section className="settings-section next-action-panel">
                <div className="section-heading">
                  <div><p className="eyebrow">Next Actions</p><h2>把判断变成学习动作</h2></div>
                  <StatusBadge tone="success">{dashboard.data.next_actions.length} 项建议</StatusBadge>
                </div>
                <p>每个动作都会创建或复用正式 PracticeUnit，完成后才能进入学习历史。</p>
                {startAction.isError && <ErrorState error={startAction.error} />}
                <div className="progress-action-list">
                  {dashboard.data.next_actions.map((action) => (
                    <article key={action.action_id}>
                      <div>
                        <div className="row-actions">
                          <StatusBadge tone={action.action_kind === 'review' ? 'warning' : 'neutral'}>
                            {action.module ? MODULE_LABELS[action.module] : '全科'}
                          </StatusBadge>
                          <small>{action.estimated_minutes} 分钟</small>
                        </div>
                        <h3>{action.title}</h3>
                        <p>{action.reason}</p>
                      </div>
                      <button
                        className="button primary"
                        disabled={startAction.isPending}
                        onClick={() => startAction.mutate(action)}
                        type="button"
                      >
                        开始 <ArrowRight size={16} />
                      </button>
                    </article>
                  ))}
                  {dashboard.data.next_actions.length === 0 && (
                    <p className="muted">当前没有待推荐的学习动作，可以自由安排练习。</p>
                  )}
                </div>
              </section>
            </>
          )}
        </section>
      )}

      {/* TAB 2: 错题复盘与队列 */}
      {activeTab === 'reviews' && (
        <section className="progress-tab-pane">
          <section className="settings-section">
            <div className="section-heading">
              <div><p className="eyebrow">Review Queue</p><h2>待复习任务</h2></div>
              <StatusBadge tone={reviewTasks.data?.length ? 'warning' : 'success'}>{reviewTasks.data?.length ?? 0} 项</StatusBadge>
            </div>
            <p>Writing V2、Reading 错题、到期听力语料和活跃错误会从正式记录自动汇总。</p>
            {reviewTasks.isPending && <LoadingState label="正在整理复习队列" />}
            {reviewTasks.isError && <ErrorState error={reviewTasks.error} />}
            {(startReview.isError || completeReview.isError) && <ErrorState error={startReview.error ?? completeReview.error} />}
            <div className="adapter-list">
              {reviewTasks.data?.map((task) => (
                <article key={task.review_task_id}>
                  <div>
                    <div className="row-actions">
                      <StatusBadge tone={task.priority >= 80 ? 'warning' : 'neutral'}>{MODULE_LABELS[task.module] ?? task.module}</StatusBadge>
                      <small>{reviewKindLabel(task.review_kind)}</small>
                    </div>
                    <h3>{task.title}</h3><p>{task.action}</p>
                  </div>
                  <div className="row-actions">
                    <button className="button primary" disabled={startReview.isPending} onClick={() => startReview.mutate(task.review_task_id)}><Play size={16} />开始</button>
                    <button className="button secondary" disabled={completeReview.isPending} onClick={() => completeReview.mutate(task.review_task_id)}><CheckCircle2 size={16} />标记完成</button>
                  </div>
                </article>
              ))}
            </div>
            {reviewTasks.data?.length === 0 && <p className="muted">当前没有待复习任务，已全部掌握！</p>}
          </section>

          {dashboard.data && (
            <section className="progress-detail-grid">
              <article className="panel error-inbox">
                <h2>错误收件箱</h2>
                {dashboard.data.errors.items.length ? dashboard.data.errors.items.slice(0, 8).map((item) => (
                  <p className="progress-row" key={`${item.module}-${item.tag}-${item.status}`}>
                    <strong>{item.tag}</strong>
                    <span>{MODULE_LABELS[item.module]} · {item.count} 次 · {errorStatusLabel(item.status)}</span>
                  </p>
                )) : <p className="muted">当前没有已记录错误。</p>}
              </article>
              <article className="panel">
                <h2>听力场景与错因</h2>
                {dashboard.data.listening.error_types.length ? dashboard.data.listening.error_types.map((item) => (
                  <p className="progress-row" key={item.type}><strong>{item.type}</strong><span>{item.count} 次</span></p>
                )) : <p className="muted">暂无拼写、定位或干扰项错因记录。</p>}
              </article>
              <article className="panel">
                <h2>阅读题型正确率</h2>
                {dashboard.data.reading_question_types.length ? dashboard.data.reading_question_types.map((item) => (
                  <p className="progress-row" key={item.question_type}>
                    <strong>{item.question_type}</strong>
                    <span>{Math.round(item.accuracy * 100)}% · {item.attempts} 题 · {item.average_seconds == null ? '未记录耗时' : `${item.average_seconds}s/题`}</span>
                  </p>
                )) : <p className="muted">暂无已判分的题型记录。</p>}
              </article>
            </section>
          )}
        </section>
      )}

      {/* TAB 3: 能力图谱与历史周报 */}
      {activeTab === 'skills' && (
        <section className="progress-tab-pane">
          <article className="settings-section weekly-report">
            <div className="section-heading">
              <div><p className="eyebrow">Weekly Review</p><h2>本周证据摘要</h2></div>
              <StatusBadge tone="neutral">{weekly.data?.period_key ?? '生成中'}</StatusBadge>
            </div>
            {weekly.isPending && <LoadingState label="正在生成结构化周报" />}
            {weekly.isError && <ErrorState error={weekly.error} />}
            {weekly.data && <WeeklySummary report={weekly.data} />}
          </article>

          {dashboard.data && (
            <article className="panel criteria-panel">
              <h2>写作 / 口语分项证据</h2>
              {(['writing', 'speaking'] as const).map((module) => (
                <div key={module} className="criterion-group">
                  <h3>{MODULE_LABELS[module]}</h3>
                  {dashboard.data.criteria[module].length ? dashboard.data.criteria[module].map((item) => (
                    <p key={item.criterion}>
                      <strong>{item.criterion}</strong>
                      <span>{item.average.toFixed(2)} · {item.samples} 个样本 · {item.evidence_class === 'progress_eligible' ? '含可信趋势' : '仅训练观察'}</span>
                    </p>
                  )) : <p className="muted">暂无结构化分项证据。</p>}
                </div>
              ))}
            </article>
          )}

          <LearningSkillMapSection />

          <section className="settings-section">
            <div className="section-heading">
              <div><p className="eyebrow">Report Archive</p><h2>周报历史</h2></div>
              <CalendarDays size={20} />
            </div>
            {weeklyHistory.isError && <ErrorState error={weeklyHistory.error} />}
            <div className="weekly-history">
              {weeklyHistory.data?.map((report) => (
                <article key={report.report_id}>
                  <strong>{report.period_key}</strong>
                  <span>{report.source_counts.completed_sessions} Sessions</span>
                  <span>{report.source_counts.completed_reviews} 次复习</span>
                  <span>{report.source_counts.estimated_minutes} 分钟</span>
                </article>
              ))}
              {weeklyHistory.data?.length === 0 && <p className="muted">还没有历史周报记录。</p>}
            </div>
          </section>

          <section className="settings-section">
            <div className="section-heading">
              <div><p className="eyebrow">Session Logs</p><h2>历史作答记录</h2></div>
            </div>
            {sessions.isPending && <LoadingState />}
            {sessions.isError && <ErrorState error={sessions.error} />}
            <div className="session-table table-scroll" tabIndex={0}>
              <table>
                <thead><tr><th>Session</th><th>科目</th><th>状态</th><th>水平</th><th>日期</th><th><span className="sr-only">操作</span></th></tr></thead>
                <tbody>{sessions.data?.map((session) => (
                  <tr key={session.session_id}>
                    <td>{session.session_id}</td>
                    <td>{MODULE_LABELS[session.module] ?? session.module}</td>
                    <td><StatusBadge tone={session.status === 'completed' ? 'success' : 'neutral'}>{session.status}</StatusBadge></td>
                    <td>{session.band ?? '—'}</td>
                    <td>{formatDate(session.occurred_at)}</td>
                    <td>{sessionDestination(session) ? <Link to={sessionDestination(session)!}>查看</Link> : <span className="muted">已记录</span>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
        </section>
      )}
    </div>
  )
}

function TrendChart({ samples, target, label }: { samples: ProgressTrendSample[]; target: number | null; label: string }) {
  const width = 360
  const height = 130
  const pad = 18
  const { points, path, targetY } = buildTrendGeometry(samples, target, width, height, pad)
  return (
    <div className="trend-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        <title>{label}</title>
        {[3, 6, 9].map((band) => {
          const y = height - pad - (band / 9) * (height - pad * 2)
          return <line className="trend-gridline" key={band} x1={pad} x2={width - pad} y1={y} y2={y} />
        })}
        {targetY != null && <line className="trend-target" x1={pad} x2={width - pad} y1={targetY} y2={targetY} />}
        {path && <path className="trend-line" d={path} />}
        {points.map((point) => (
          <circle
            className={point.eligible ? 'trend-point eligible' : 'trend-point observation'}
            cx={point.x}
            cy={point.y}
            key={point.session_id}
            r={point.eligible ? 4 : 3.5}
          >
            <title>{`${formatDate(point.occurred_at)}：${point.band.toFixed(1)}（${point.eligible ? '可信成绩' : '训练观察'}）`}</title>
          </circle>
        ))}
      </svg>
      {!samples.length && <span className="trend-empty">还没有可绘制的成绩</span>}
    </div>
  )
}

function LearningSkillMapSection() {
  const [dimension, setDimension] = useState<(typeof LEARNING_DIMENSIONS)[number]['id']>('reading')
  const learningModel = useQuery({
    queryKey: ['learning-model'],
    queryFn: () => api<LearningModelSnapshot>('/api/v1/learning-model'),
    staleTime: 30_000,
  })
  const skills = learningModel.data?.skills.filter((item) => item.dimension_id === dimension) ?? []
  const evidenceCount = skills.reduce((total, item) => total + (item.mastery?.evidence_count ?? 0), 0)

  return (
    <section className="learning-skill-section" aria-labelledby="learning-skill-title">
      <div className="learning-skill-heading">
        <div>
          <p className="eyebrow">Skill Evidence</p>
          <h2 id="learning-skill-title">能力形成到哪一步</h2>
          <p>掌握度来自多次学习证据，不等同于任何正式考试成绩；证据不足时不会强行判断。</p>
        </div>
        <ListChecks size={21} aria-hidden="true" />
      </div>
      <div className="learning-dimension-tabs" aria-label="选择能力模块">
        {LEARNING_DIMENSIONS.map((item) => (
          <button
            className={dimension === item.id ? 'active' : ''}
            key={item.id}
            type="button"
            aria-pressed={dimension === item.id}
            onClick={() => setDimension(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {learningModel.isPending && <LoadingState label="正在整理能力证据" />}
      {learningModel.isError && <ErrorState error={learningModel.error} />}
      {learningModel.data && (
        <div className="learning-skill-body">
          <div className="learning-skill-summary">
            <strong>{dimensionLabel(dimension)}</strong>
            <span>{evidenceCount > 0 ? `${evidenceCount} 条有效学习证据` : '等待第一次有效练习'}</span>
          </div>
          <div className="learning-skill-list">
            {skills.map((skill) => {
              const mastery = masteryPresentation(skill)
              const copy = skillPresentation(skill)
              return (
                <article className={`learning-skill-row ${mastery.tone}`} key={skill.skill_id}>
                  <div className="learning-skill-copy">
                    <strong>{copy.title}</strong>
                    <small>{copy.description}</small>
                  </div>
                  <div className="learning-skill-measure">
                    <span><strong>{mastery.label}</strong>{mastery.percent > 0 ? ` · ${mastery.percent}%` : ''}</span>
                    <div aria-hidden="true"><i style={{ width: `${mastery.percent}%` }} /></div>
                    <small>{mastery.detail}</small>
                  </div>
                </article>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}

function TrendDirection({ direction, delta }: { direction: string; delta: number | null }) {
  if (direction === 'improving') return <span className="trend-direction positive"><TrendingUp size={15} />提升 {delta?.toFixed(2)}</span>
  if (direction === 'declining') return <span className="trend-direction negative"><TrendingDown size={15} />下降 {Math.abs(delta ?? 0).toFixed(2)}</span>
  if (direction === 'stable') return <span className="trend-direction">基本稳定</span>
  return <span className="trend-direction">证据不足</span>
}

function WeeklySummary({ report }: { report: WeeklyReport }) {
  return (
    <>
      <div className="weekly-facts">
        <span><strong>{report.source_counts.completed_sessions}</strong> Sessions</span>
        <span><strong>{report.source_counts.completed_practice_units}</strong> 学习单元</span>
        <span><strong>{report.source_counts.completed_reviews}</strong> 完成复习</span>
        <span><strong>{report.source_counts.estimated_minutes}</strong> 分钟</span>
      </div>
      <div className="weekly-evidence-columns">
        <div><h3>进展</h3>{report.wins.length ? <ul>{report.wins.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">本周还没有足够证据判断提升。</p>}</div>
        <div><h3>风险</h3>{report.risks.length ? <ul>{report.risks.map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">本周没有新增风险。</p>}</div>
      </div>
    </>
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

function errorStatusLabel(value: string) {
  return ({ active: '待处理', monitoring: '观察中', resolved: '已解决' } as Record<string, string>)[value] ?? value
}

function reviewKindLabel(value: ReviewTask['review_kind']) {
  return ({
    error_review: '错误复盘',
    listening_expression: '听力到期复习',
    writing_revision: 'Writing V2',
    reading_wrong_answer: 'Reading 错题',
  } as Record<ReviewTask['review_kind'], string>)[value]
}
