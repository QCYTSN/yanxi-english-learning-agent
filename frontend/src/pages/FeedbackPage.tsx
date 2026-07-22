import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Target } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { api, type SessionSummary } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type Anchor = { quote: string; start: number; end: number; status?: string }
type WritingReview = {
  estimated_band?: { low: number; high: number }
  confidence: string
  criteria: Array<{ criterion: string; score_low: number; score_high: number; evidence_support: string[]; evidence_limit: string[]; anchors?: Anchor[] }>
  priority_issues: Array<{ tag: string; evidence: string; learner_action: string; anchor?: Anchor }>
}
type ReadingReview = { items: Array<{ question_number?: string | number; question_type: string; user_answer?: unknown; correct_answer?: unknown; evidence_location?: string; evidence?: string; reasoning?: string; next_rule?: string }> }

export function FeedbackPage() {
  const { sessionId = '' } = useParams()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session', sessionId], queryFn: () => api<SessionSummary>(`/api/v1/sessions/${sessionId}`) })
  const finish = useMutation({
    mutationFn: () => api<SessionSummary>(`/api/v1/sessions/${sessionId}/finish`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })
  if (session.isPending) return <LoadingState />
  if (session.isError) return <ErrorState error={session.error} />
  const isWriting = session.data.module === 'writing'
  return (
    <div className="page">
      <PageHeader eyebrow={sessionId} title={isWriting ? '写作反馈' : '阅读复盘'} description="正式反馈来自已经通过 Schema 和语义验证的 Session 数据。" action={session.data.status !== 'completed' ? <button className="button secondary" onClick={() => finish.mutate()}><CheckCircle2 size={18} />完成本次练习</button> : <StatusBadge tone="success">已完成</StatusBadge>} />
      {finish.isError && <ErrorState error={finish.error} />}
      {isWriting ? <WritingFeedback session={session.data} /> : <ReadingFeedback session={session.data} />}
    </div>
  )
}

function WritingFeedback({ session }: { session: SessionSummary }) {
  const review = session.writing_review as WritingReview | undefined
  const versions = (session.versions as Array<{ label: string; content: string }> | undefined) ?? []
  const scored = versions.find((item) => item.label === session.scored_version) ?? versions.at(-1)
  if (!review || !scored) return <div className="empty-state"><h2>反馈尚未准备好</h2><p>返回工作区提交作文并生成反馈。</p></div>
  const primaryAnchor = review.priority_issues.find((item) => item.anchor)?.anchor
  return (
    <>
      <div className="feedback-grid">
        <article className="evidence-document">
          <p className="eyebrow">{scored.label} · learner text</p>
          <AnchoredText text={scored.content} anchor={primaryAnchor} />
        </article>
        <aside className="evidence-rail">
          <div className="band-summary"><span>估分区间</span><strong>{review.estimated_band ? `${review.estimated_band.low}–${review.estimated_band.high}` : '定性反馈'}</strong><StatusBadge>{review.confidence} confidence</StatusBadge></div>
          <h2>四项证据</h2>
          {review.criteria.map((criterion) => <article key={criterion.criterion} className="criterion-card"><div><strong>{criterion.criterion}</strong><span>{criterion.score_low}–{criterion.score_high}</span></div><p>{criterion.evidence_support[0]}</p><p className="limit">{criterion.evidence_limit[0]}</p></article>)}
        </aside>
      </div>
      <section className="priorities"><div className="section-heading"><div><p className="eyebrow">Revise</p><h2>本轮优先处理</h2></div></div>{review.priority_issues.map((issue, index) => <article key={issue.tag}><span>{index + 1}</span><div><h3>{issue.tag}</h3><p>{issue.evidence}</p><strong><Target size={16} />{issue.learner_action}</strong></div></article>)}</section>
      {versions.length > 1 && <section className="version-comparison"><h2>V1 / V2 对比</h2><div><article><h3>V1</h3><p>{versions.find((item) => item.label === 'v1')?.content}</p></article><article><h3>V2</h3><p>{versions.find((item) => item.label === 'v2')?.content}</p></article></div></section>}
      {session.status !== 'completed' && <div className="next-step-card"><div><h2>由你完成下一版</h2><p>模型替代答案仍未开放；先根据三个重点修改自己的文本。</p></div><Link className="button primary" to={`/practice/writing/${session.session_id}`}>返回修改</Link></div>}
    </>
  )
}

function ReadingFeedback({ session }: { session: SessionSummary }) {
  const review = session.reading_review as ReadingReview | undefined
  if (!review) return <div className="empty-state"><h2>复盘尚未准备好</h2><p>提交答案并生成结构化复盘后再查看。</p></div>
  return <div className="reading-review-list">{review.items.map((item, index) => <article key={`${item.question_number}-${index}`}><div className="review-number">{item.question_number ?? index + 1}</div><div><div className="answer-line"><span>你的答案 <strong>{String(item.user_answer ?? '—')}</strong></span><span>正确答案 <strong>{String(item.correct_answer ?? '—')}</strong></span></div><p className="evidence-location">{item.evidence_location}</p><p>{item.evidence}</p><p>{item.reasoning}</p><div className="next-rule"><Target size={17} /><span>{item.next_rule}</span></div></div></article>)}</div>
}

function AnchoredText({ text, anchor }: { text: string; anchor?: Anchor }) {
  if (!anchor || anchor.status === 'ambiguous' || text.slice(anchor.start, anchor.end) !== anchor.quote) return <p className="essay-review-text">{text}</p>
  return <p className="essay-review-text">{text.slice(0, anchor.start)}<mark id="primary-evidence">{text.slice(anchor.start, anchor.end)}</mark>{text.slice(anchor.end)}</p>
}
