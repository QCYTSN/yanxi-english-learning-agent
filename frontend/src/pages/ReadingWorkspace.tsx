import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Lightbulb, Send, TimerReset } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type Draft, type Question, type SessionSummary } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { ConformanceBadge, ErrorState, LoadingState, PageHeader, PhaseRail, SaveState } from '../components/Common'

type Conformance = { status?: string; errors?: string[]; warnings?: string[]; metrics?: Record<string, unknown> }
type ReadingSet = {
  passage: { passage_id: string; title?: string; body: string }
  questions: Question[]
  conformance?: Conformance
}

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
  const locked = status === 'awaiting_feedback' || status === 'awaiting_revision' || status === 'completed'
  const practiceMode = String(session.data.practice_mode ?? 'section_practice')
  const conformanceStatus = String(session.data.conformance_status ?? readingSet.data?.conformance?.status ?? 'provisional')
  return (
    <div className="workspace-page">
      <PageHeader
        eyebrow={sessionId}
        title="Reading 工作区"
        description={timed ? '20 分钟篇章专项：提交前不提供提示或答案。它不是三篇、40 题的完整模考。' : '引导练习：提示逐级增加，正式提交前不会揭示答案。'}
        action={<div className="header-badges"><ConformanceBadge status={conformanceStatus} mode={practiceMode} /><SaveState state={saveState} /></div>}
      />
      <PhaseRail active={status === 'awaiting_revision' ? '复盘' : status === 'awaiting_feedback' ? '反馈' : '作答'} phases={['阅读', '作答', '反馈', '复盘', '完成']} />
      {conformanceStatus !== 'verified' && <p className="conformance-note">当前材料可用于专项训练，但未被标记为可换算 IELTS Band 的完整套题。</p>}
      <div className="reading-grid">
        <article className="passage-panel">
          <p className="eyebrow">{readingSet.data?.passage.passage_id}</p>
          <h2>{readingSet.data?.passage.title ?? 'Reading passage'}</h2>
          <div className="passage-text">{paragraphs(readingSet.data?.passage.body ?? '').map((paragraph, index) => <p key={index}><span className="paragraph-label">{String.fromCharCode(65 + index)}</span>{paragraph}</p>)}</div>
        </article>
        <section className="questions-panel" aria-label="阅读题目">
          <div className="questions-toolbar"><span>{answered}/{questions.length} 已作答</span><span><TimerReset size={16} />{timed ? '20 分钟目标' : '自主练习'}</span></div>
          {questions.map((question, index) => (
            <ReadingQuestion
              key={question.question_id}
              question={question}
              index={index}
              value={answers[question.question_id] ?? ''}
              disabled={locked}
              onChange={(value) => setAnswers((current) => ({ ...current, [question.question_id]: value }))}
            />
          ))}
          <div className="questions-footer">
            <SaveState state={saveState} />
            {!timed && Number(session.data.hints_used ?? 0) < 3 && !locked && <button className="button secondary" onClick={() => hint.mutate()} disabled={hint.isPending}><Lightbulb size={18} />记录提示 {Number(session.data.hints_used ?? 0) + 1}</button>}
            <button className="button primary" onClick={() => submit.mutate()} disabled={!answered || submit.isPending || locked}><Send size={18} />提交答案</button>
          </div>
          {hint.isSuccess && <p className="inline-note" aria-live="polite">提示级别已记录。答案仍保持锁定；Reading Agent 只负责基于原文解释，不负责猜答案键。</p>}
          {(hint.isError || submit.isError) && <ErrorState error={hint.error ?? submit.error} />}
        </section>
      </div>
      {status === 'awaiting_feedback' && <AgentPanel sessionId={sessionId} contract="reading-review@1" action="wrong_answer_review" onPersisted={refresh} />}
      {status === 'awaiting_revision' && <div className="next-step-card"><div><h2>复盘已保存</h2><p>查看答案键判分、原文证据、错误原因和下次规则。</p></div><Link className="button primary" to={`/feedback/${sessionId}`}>查看复盘</Link></div>}
    </div>
  )
}

function ReadingQuestion({ question, index, value, disabled, onChange }: {
  question: Question
  index: number
  value: string
  disabled: boolean
  onChange: (value: string) => void
}) {
  const type = question.question_type ?? 'unknown'
  const options = normaliseOptions(question.options)
  const truthOptions = type === 'true_false_not_given' ? ['TRUE', 'FALSE', 'NOT GIVEN'] : type === 'yes_no_not_given' ? ['YES', 'NO', 'NOT GIVEN'] : null
  const optionSet = truthOptions?.map((item) => ({ key: item, text: item })) ?? options
  const wordLimit = question.answer_constraints?.word_limit
  return (
    <fieldset className="reading-question" disabled={disabled}>
      <legend><strong>{question.question_number ?? index + 1}</strong><span>{question.content}</span></legend>
      {optionSet.length > 0 ? (
        <div className="answer-options">
          {optionSet.map((option) => <label key={option.key}><input type="radio" name={`answer-${question.question_id}`} value={option.key} checked={value === option.key} onChange={() => onChange(option.key)} /><span><b>{option.key}</b>{option.text !== option.key && option.text}</span></label>)}
        </div>
      ) : (
        <input id={`answer-${question.question_id}`} value={value} onChange={(event) => onChange(event.target.value)} placeholder={wordLimit ? `不超过 ${wordLimit} 个词` : '输入答案'} autoComplete="off" />
      )}
      {wordLimit && <small className="answer-constraint">NO MORE THAN {wordLimit === 1 ? 'ONE WORD' : `${wordLimit} WORDS`}{question.answer_constraints?.words_from_passage ? ' FROM THE PASSAGE' : ''}</small>}
    </fieldset>
  )
}

function normaliseOptions(options: Question['options']): Array<{ key: string; text: string }> {
  if (Array.isArray(options)) return options
  return Object.entries(options ?? {}).map(([key, text]) => ({ key, text: String(text) }))
}

function paragraphs(value: string) { return value.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean) }
