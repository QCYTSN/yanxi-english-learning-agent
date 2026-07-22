import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Lightbulb, Send, TimerReset } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type Draft, type Question, type SessionSummary } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { ErrorState, LoadingState, PageHeader, PhaseRail, SaveState } from '../components/Common'

type ReadingSet = { passage: { passage_id: string; title?: string; body: string }; questions: Question[] }

export function ReadingWorkspace() {
  const { sessionId = '' } = useParams()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session', sessionId], queryFn: () => api<SessionSummary>(`/api/v1/sessions/${sessionId}`) })
  const readingSet = useQuery({
    queryKey: ['passage', session.data?.passage_id],
    queryFn: () => api<ReadingSet>(`/api/v1/passages/${session.data?.passage_id}`),
    enabled: Boolean(session.data?.passage_id),
  })
  const draft = useQuery({ queryKey: ['draft', sessionId, 'reading'], queryFn: () => api<Draft>(`/api/v1/sessions/${sessionId}/draft/reading`) })
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [draftRevision, setDraftRevision] = useState(0)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const initialized = useRef(false)
  const lastSaved = useRef('')

  useEffect(() => {
    if (!draft.data || initialized.current) return
    const saved = (draft.data.payload.answers as Record<string, string> | undefined) ?? {}
    setAnswers(saved)
    setDraftRevision(draft.data.revision)
    lastSaved.current = JSON.stringify(saved)
    initialized.current = true
    setSaveState(draft.data.updated_at ? 'saved' : 'idle')
  }, [draft.data])

  useEffect(() => {
    const serialized = JSON.stringify(answers)
    if (!initialized.current || serialized === lastSaved.current) return
    setSaveState('saving')
    const timer = window.setTimeout(async () => {
      try {
        const saved = await api<Draft>(`/api/v1/sessions/${sessionId}/draft`, {
          method: 'PUT',
          body: jsonBody({ draft_kind: 'reading', expected_revision: draftRevision, payload: { answers } }),
        })
        setDraftRevision(saved.revision)
        lastSaved.current = serialized
        setSaveState('saved')
      } catch { setSaveState('error') }
    }, 650)
    return () => window.clearTimeout(timer)
  }, [answers, draftRevision, sessionId])

  const hint = useMutation({
    mutationFn: () => api<SessionSummary>(`/api/v1/reading/${sessionId}/hints`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({ level: Math.min(Number(session.data?.hints_used ?? 0) + 1, 3), expected_revision: session.data?.revision ?? 0 }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })
  const submit = useMutation({
    mutationFn: () => {
      const questions = readingSet.data?.questions ?? []
      const payload = questions.filter((item) => answers[item.question_id]).map((item, index) => ({
        question_id: item.question_id,
        question_number: item.question_number ?? index + 1,
        question_type: item.question_type ?? 'unknown',
        user_answer: answers[item.question_id],
      }))
      return api<SessionSummary>(`/api/v1/reading/${sessionId}/answers`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey() },
        body: jsonBody({ answers: payload, expected_revision: session.data?.revision ?? 0 }),
      })
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
  if (session.isPending || draft.isPending || readingSet.isPending) return <LoadingState />
  if (session.isError) return <ErrorState error={session.error} />
  if (readingSet.isError) return <ErrorState error={readingSet.error} />
  const status = session.data.status
  const timed = session.data.mode === 'timed-practice'
  const questions = readingSet.data?.questions ?? []
  const answered = Object.values(answers).filter(Boolean).length
  return (
    <div className="workspace-page">
      <PageHeader eyebrow={sessionId} title="Reading 工作区" description={timed ? '严格计时模式：完整提交前不提供提示或答案。' : '引导模式：提示逐级增加，但不会提前揭示答案。'} action={<SaveState state={saveState} />} />
      <PhaseRail active={status === 'awaiting_revision' ? '复盘' : status === 'awaiting_feedback' ? '反馈' : '作答'} phases={['阅读', '作答', '反馈', '复盘', '完成']} />
      <div className="reading-grid">
        <article className="passage-panel">
          <p className="eyebrow">{readingSet.data?.passage.passage_id}</p>
          <h2>{readingSet.data?.passage.title ?? 'Reading passage'}</h2>
          <div className="passage-text">{paragraphs(readingSet.data?.passage.body ?? '').map((paragraph, index) => <p key={index}><span className="paragraph-label">{String.fromCharCode(65 + index)}</span>{paragraph}</p>)}</div>
        </article>
        <section className="questions-panel" aria-label="阅读题目">
          <div className="questions-toolbar"><span>{answered}/{questions.length} 已作答</span><span><TimerReset size={16} />{timed ? '20:00' : '自主练习'}</span></div>
          {questions.map((question, index) => (
            <div className="reading-question" key={question.question_id}>
              <label htmlFor={`answer-${question.question_id}`}><strong>{question.question_number ?? index + 1}</strong>{question.content}</label>
              <input id={`answer-${question.question_id}`} value={answers[question.question_id] ?? ''} onChange={(event) => setAnswers((current) => ({ ...current, [question.question_id]: event.target.value }))} placeholder="输入答案" autoComplete="off" />
            </div>
          ))}
          <div className="questions-footer"><SaveState state={saveState} />{!timed && Number(session.data.hints_used ?? 0) < 3 && <button className="button secondary" onClick={() => hint.mutate()} disabled={hint.isPending}><Lightbulb size={18} />记录提示 {Number(session.data.hints_used ?? 0) + 1}</button>}<button className="button primary" onClick={() => submit.mutate()} disabled={!answered || submit.isPending || status === 'awaiting_feedback'}><Send size={18} />提交答案</button></div>
          {hint.isSuccess && <p className="inline-note" aria-live="polite">提示级别已记录。正式解释需要通过 Reading Agent 生成，答案仍未揭示。</p>}
          {(hint.isError || submit.isError) && <ErrorState error={hint.error ?? submit.error} />}
        </section>
      </div>
      {status === 'awaiting_feedback' && <AgentPanel sessionId={sessionId} contract="reading-review@1" action="wrong_answer_review" onPersisted={refresh} />}
      {status === 'awaiting_revision' && <div className="next-step-card"><div><h2>复盘已保存</h2><p>查看题目证据、错误原因和下次规则。</p></div><Link className="button primary" to={`/feedback/${sessionId}`}>查看复盘</Link></div>}
    </div>
  )
}

function paragraphs(value: string) { return value.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean) }
