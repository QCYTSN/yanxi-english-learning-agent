import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark, CheckCircle2, Headphones, Send, TimerReset, Volume2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type AssessmentRun, type Question } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge, StructuredTaskVisual } from '../components/Common'
import { AgentPanel } from '../components/AgentPanel'

export function AssessmentRunnerPage() {
  const { runId = '' } = useParams()
  const queryClient = useQueryClient()
  const run = useQuery({
    queryKey: ['assessment-run', runId],
    queryFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${runId}`),
    refetchInterval: 15_000,
  })
  const [sectionKey, setSectionKey] = useState('')
  const [questionId, setQuestionId] = useState('')
  const [clock, setClock] = useState(Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  useEffect(() => {
    if (!run.data || sectionKey) return
    const first = run.data.sections[0]?.section_key ?? ''
    setSectionKey(String(run.data.navigation.section_key ?? first))
  }, [run.data, sectionKey])
  const questions = useMemo(
    () => run.data?.pack_snapshot.questions.filter((item) => questionSection(run.data!.module, item) === sectionKey) ?? [],
    [run.data, sectionKey],
  )
  useEffect(() => {
    if (!questions.length) return
    if (!questions.some((item) => item.question_id === questionId)) setQuestionId(questions[0].question_id)
  }, [questions, questionId])
  const submit = useMutation({
    mutationFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${runId}/submit`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
    }),
    onSuccess: (value) => queryClient.setQueryData(['assessment-run', runId], value),
  })
  const autoSubmitted = useRef(false)
  useEffect(() => {
    const value = run.data
    if (
      !value
      || value.status !== 'active'
      || !value.timer.expired
      || autoSubmitted.current
      || submit.isPending
    ) return
    autoSubmitted.current = true
    submit.mutate()
  }, [run.data, submit])
  if (run.isPending) return <LoadingState label="正在恢复完整模考" />
  if (run.isError) return <ErrorState error={run.error} />
  const value = run.data
  const current = value.pack_snapshot.questions.find((item) => item.question_id === questionId)
  const answered = value.responses.filter((item) => hasAnswer(item.response)).length
  const total = value.pack_snapshot.questions.length
  const terminal = ['submitted', 'completed', 'reviewing', 'expired', 'cancelled'].includes(value.status)
  const answersLocked = terminal || value.timer.expired
  const remaining = displayedRemaining(value, clock)
  return <div className="assessment-page">
    <PageHeader
      eyebrow={`${value.module.toUpperCase()} · ${value.run_id}`}
      title={value.pack_snapshot.title}
      description={`内容已冻结为 ${value.pack_hash.slice(0, 12)}…；计时、回答和播放状态由本地 Runtime 持久化。`}
      action={<div className="header-badges"><StatusBadge tone={terminal ? 'success' : 'warning'}>{value.timer.expired && value.status === 'active' ? 'time ended' : value.status}</StatusBadge><span className="timer-chip"><TimerReset size={17} />{remaining === null ? (value.module === 'speaking' ? 'Voice / Live 计时' : '音频主导') : formatTime(remaining)}</span></div>}
    />
    <div className="assessment-summary">
      <strong>{answered}/{total}</strong><span>已作答</span>
      <span>统一 Session：{value.session_id}</span>
      <span>{value.timer.pause_allowed ? '可暂停练习' : '严格模式不可暂停'}</span>
    </div>
    <nav className="section-rail" aria-label="模考部分">
      {value.sections.map((section, index) => <button key={section.section_key} className={sectionKey === section.section_key ? 'active' : ''} onClick={() => { setSectionKey(section.section_key); void saveNavigation(value, section.section_key, questionId) }}><strong>{index + 1}</strong><span>{sectionLabel(value.module, section.section_key)}</span></button>)}
    </nav>
    {value.status === 'completed'
      ? value.module === 'writing' || value.module === 'speaking'
        ? <ReviewedResult run={value} />
        : <ObjectiveResult run={value} />
      : value.status === 'reviewing' && value.module === 'writing'
        ? <WritingScorePanel run={value} />
        : value.status === 'reviewing' && value.module === 'speaking'
          ? <SpeakingReportPanel run={value} />
          : <div className="assessment-workspace">
              <ContextPanel run={value} sectionKey={sectionKey} />
              <section className="assessment-questions">
                <div className="question-number-grid">{questions.map((question, index) => {
                  const response = value.responses.find((item) => item.question_id === question.question_id)
                  return <button key={question.question_id} className={`${questionId === question.question_id ? 'active' : ''} ${hasAnswer(response?.response) ? 'answered' : ''} ${response?.flagged ? 'flagged' : ''}`} onClick={() => { setQuestionId(question.question_id); void saveNavigation(value, sectionKey, question.question_id) }}>{question.question_number ?? index + 1}</button>
                })}</div>
                {current && <AssessmentQuestion run={value} question={current} disabled={answersLocked} onSaved={() => void run.refetch()} />}
                {!current && value.module === 'speaking' && <SpeakingHandoffPanel run={value} onCreated={() => void run.refetch()} />}
              </section>
            </div>}
    {!terminal && <div className="assessment-submit-bar"><div><strong>{value.timer.expired ? '时间到，正在提交' : '提交整套答案'}</strong><p>{value.timer.expired ? '答案已冻结；Runtime 会保存已答和未答状态，提交按钮不会消失。' : '提交后答案键和证据才会解锁；未答题会按未作答保存。'}</p></div><button className="button primary" disabled={submit.isPending} onClick={() => (value.timer.expired || window.confirm(`确认提交？当前已答 ${answered}/${total} 题。`)) && submit.mutate()}><Send size={18} />{submit.isPending ? '提交中' : '提交模考'}</button></div>}
    {submit.isError && <ErrorState error={submit.error} />}
  </div>
}

function ContextPanel({ run, sectionKey }: { run: AssessmentRun; sectionKey: string }) {
  if (run.module === 'reading') {
    const passage = run.pack_snapshot.passages?.[sectionKey]
    return <article className="assessment-context passage-panel"><p className="eyebrow">{sectionKey}</p><h2>{passage?.title ?? 'Reading passage'}</h2><div className="passage-text">{readingParagraphs(passage?.body ?? '').map((item, index) => <p className={item.label ? 'labelled' : undefined} key={index}>{item.label && <span className="paragraph-label">{item.label}</span>}{item.text}</p>)}</div></article>
  }
  if (run.module === 'listening') {
    const section = run.sections.find((item) => item.section_key === sectionKey)
    return <AudioPanel run={run} mediaId={String(section?.payload.audio_media_id ?? '')} />
  }
  if (run.module === 'writing') {
    const question = run.pack_snapshot.questions.find((item) => item.task === sectionKey)
    const firstMedia = question?.media_id ?? (Array.isArray(question?.media_ids) ? question.media_ids[0] : null)
    return <article className="assessment-context writing-guidance">
      <p className="eyebrow">{sectionKey}</p>
      <h2>{sectionKey === 'task1' ? '建议 20 分钟 · 至少 150 词' : '建议 40 分钟 · 至少 250 词'}</h2>
      <p className="task-prompt">{question?.content}</p>
      {question?.task_data && <StructuredTaskVisual data={question.task_data} />}
      {firstMedia && <a className="media-preview" href={`/api/v1/media/${String(firstMedia)}/content`} target="_blank" rel="noreferrer"><img src={`/api/v1/media/${String(firstMedia)}/content`} alt="Task 1 registered visual" /></a>}
      <p>两项任务共用 60 分钟，Runtime 不会在 20/40 分钟处强制切断。</p>
    </article>
  }
  return <article className="assessment-context writing-guidance"><p className="eyebrow">External Voice / Live</p><h2>11–14 分钟连续模考</h2><p>中途不纠错。计时和语音交互由外部主持方完成，结果导回同一个 AssessmentRun。</p></article>
}

function AssessmentQuestion({ run, question, disabled, onSaved }: { run: AssessmentRun; question: Question; disabled: boolean; onSaved: () => void }) {
  const existing = run.responses.find((item) => item.question_id === question.question_id)
  const initial = existing?.response.text ?? existing?.response.answer ?? ''
  const [answer, setAnswer] = useState<string | string[]>(initial)
  const [flagged, setFlagged] = useState(Boolean(existing?.flagged))
  useEffect(() => {
    setAnswer(existing?.response.text ?? existing?.response.answer ?? '')
    setFlagged(Boolean(existing?.flagged))
  }, [question.question_id, existing?.revision, existing?.response.text, existing?.response.answer, existing?.flagged])
  const save = useMutation({
    mutationFn: (override?: { answer?: string | string[]; flagged?: boolean }) => api(`/api/v1/assessment-runs/${run.run_id}/responses/${question.question_id}`, {
      method: 'PUT',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({
        section_key: questionSection(run.module, question),
        response: run.module === 'writing' ? { text: override?.answer ?? answer } : { answer: override?.answer ?? answer },
        expected_revision: existing?.revision ?? 0,
        flagged: override?.flagged ?? flagged,
      }),
    }),
    onSuccess: onSaved,
  })
  if (run.module === 'speaking') return <SpeakingHandoffPanel run={run} onCreated={onSaved} />
  const options = normaliseOptions(question)
  const multiple = Number(question.answer_constraints?.answer_count ?? question.selection_count ?? 1) > 1
  const groupDisplay = String(
    question.question_group_display_text ?? question.source_group_text ?? '',
  ).trim()
  const sourceGroup = run.module === 'reading' && groupDisplay
    ? <aside className="reading-question-source">
        <div>
          <strong>
            Questions {question.question_group_start ?? question.question_number}
            {question.question_group_end && question.question_group_end !== question.question_group_start
              ? `–${question.question_group_end}`
              : ''}
          </strong>
          <span>{String(question.question_type ?? '').replaceAll('_', ' ')}</span>
        </div>
        <p>{groupDisplay}</p>
      </aside>
    : null
  return <article className="assessment-question-card">
    <div className="question-meta"><span>Question {question.question_number ?? question.question_id}</span><button disabled={disabled || save.isPending} className={flagged ? 'flag-button active' : 'flag-button'} onClick={() => { const next = !flagged; setFlagged(next); save.mutate({ flagged: next }) }}><Bookmark size={16} />{flagged ? '已标记' : '稍后检查'}</button></div>
    {sourceGroup}
    <h2>{question.content}</h2>
    {run.module === 'writing'
      ? <><textarea className="assessment-editor" value={String(answer)} onChange={(event) => setAnswer(event.target.value)} onBlur={() => save.mutate(undefined)} disabled={disabled} aria-label={`${question.task} 作文`} /><div className="editor-footer"><span>{wordCount(String(answer))} words</span><button className="button secondary" onClick={() => save.mutate(undefined)} disabled={disabled || save.isPending}>保存</button></div></>
      : options.length
        ? <div className="answer-options">{options.map((option) => {
            const selected = Array.isArray(answer) ? answer.includes(option.key) : answer === option.key
            return <label key={option.key}><input type={multiple ? 'checkbox' : 'radio'} checked={selected} disabled={disabled || save.isPending} onChange={() => {
              const next = multiple
                ? (Array.isArray(answer) ? (selected ? answer.filter((item) => item !== option.key) : [...answer, option.key]) : [option.key])
                : option.key
              setAnswer(next)
              save.mutate({ answer: next })
            }} /><span><b>{option.key}</b>{option.text !== option.key ? option.text : null}</span></label>
          })}</div>
        : <div className="answer-entry"><input value={String(answer)} onChange={(event) => setAnswer(event.target.value)} onBlur={() => save.mutate(undefined)} disabled={disabled} placeholder={question.answer_constraints?.word_limit ? `不超过 ${question.answer_constraints.word_limit} 个词` : '输入答案'} /><button className="button secondary" onClick={() => save.mutate(undefined)} disabled={disabled || save.isPending}>保存</button></div>}
    {save.isError && <ErrorState error={save.error} />}
  </article>
}

function AudioPanel({ run, mediaId }: { run: AssessmentRun; mediaId: string }) {
  const queryClient = useQueryClient()
  const audioRef = useRef<HTMLAudioElement>(null)
  const state = run.media_state[mediaId] ?? {}
  const [leaseToken, setLeaseToken] = useState(run.playback_lease?.token ?? '')
  const start = useMutation({
    mutationFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}/start`, { method: 'POST' }),
    onSuccess: (value) => {
      setLeaseToken(value.playback_lease?.token ?? '')
      queryClient.setQueryData(['assessment-run', run.run_id], value)
    },
  })
  const renew = useMutation({
    mutationFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}/lease`, { method: 'POST' }),
    onSuccess: (value) => {
      setLeaseToken(value.playback_lease?.token ?? '')
      queryClient.setQueryData(['assessment-run', run.run_id], value)
    },
  })
  const lastSent = useRef(Number(state.position_seconds ?? 0))
  useEffect(() => {
    if (state.play_count === 1 && !state.completed && !leaseToken && !renew.isPending && !renew.isError) renew.mutate()
  }, [leaseToken, renew, state.completed, state.play_count])
  function update(completed = false) {
    const position = audioRef.current?.currentTime ?? lastSent.current
    if (!completed && position - lastSent.current < 5) return
    lastSent.current = position
    void api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}`, {
      method: 'PUT',
      body: jsonBody({ position_seconds: position, completed }),
    }).then((value) => queryClient.setQueryData(['assessment-run', run.run_id], value))
  }
  return <article className="assessment-context audio-runner">
    <Headphones size={28} />
    <p className="eyebrow">一次播放 · 安全租约</p>
    <h2>Listening audio</h2>
    <p>浏览器可发起多次 Range 请求，但播放次数只计一次。刷新页面会从服务端记录的位置续播，租约不能跨 AssessmentRun 使用。</p>
    {!state.play_count
      ? <button className="button primary" disabled={!mediaId || start.isPending} onClick={() => start.mutate()}><Volume2 size={18} />开始唯一一次播放</button>
      : leaseToken && !state.completed
        ? <audio
            ref={audioRef}
            src={`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}/content?lease=${encodeURIComponent(leaseToken)}`}
            controls
            autoPlay
            onLoadedMetadata={(event) => { event.currentTarget.currentTime = Number(state.position_seconds ?? 0) }}
            onTimeUpdate={() => update(false)}
            onEnded={() => update(true)}
            onSeeking={(event) => {
              if (event.currentTarget.currentTime + 0.5 < Number(state.position_seconds ?? 0)) {
                event.currentTarget.currentTime = Number(state.position_seconds ?? 0)
              }
            }}
            onError={() => { if (!renew.isPending) renew.mutate() }}
          />
        : !state.completed
          ? <p>正在恢复本次播放的安全租约…</p>
          : null}
    {state.completed && <StatusBadge tone="success">播放已完成</StatusBadge>}
    {start.isError && <ErrorState error={start.error} />}
    {renew.isError && <ErrorState error={renew.error} />}
  </article>
}

function ObjectiveResult({ run }: { run: AssessmentRun }) {
  const results = Array.isArray(run.score_result.question_results)
    ? run.score_result.question_results as Array<Record<string, unknown>>
    : []
  const questionById = new Map(run.pack_snapshot.questions.map((question) => [question.question_id, question]))
  const grouped = new Map<string, Array<Record<string, unknown>>>()
  for (const section of run.sections) grouped.set(section.section_key, [])
  for (const item of results) {
    const question = questionById.get(String(item.question_id))
    const key = question ? questionSection(run.module, question) : 'results'
    const group = grouped.get(key) ?? []
    group.push(item)
    grouped.set(key, group)
  }
  const groups = [...grouped.entries()].filter(([, items]) => items.length > 0)
  const correct = results.filter((item) => item.is_correct === true).length
  const unanswered = results.filter((item) => !displayAnswer(item.user_answer)).length
  return <section className="assessment-result">
    <div className="result-hero">
      <CheckCircle2 />
      <div>
        <h2>{String(run.score_result.raw_score ?? correct)} / {String(run.score_result.total ?? results.length)}</h2>
        <p>{run.score_result.band ? `IELTS 训练估分 ${String(run.score_result.band)}` : '已保存原始分；套题没有经审核的换算表，因此不生成 Band。'}</p>
      </div>
      <dl className="result-breakdown" aria-label="答题结果概览">
        <div><dt>正确</dt><dd>{correct}</dd></div>
        <div><dt>错误</dt><dd>{Math.max(0, results.length - correct - unanswered)}</dd></div>
        <div><dt>未答</dt><dd>{unanswered}</dd></div>
      </dl>
    </div>
    <div className="result-groups">
      {groups.map(([key, items]) => {
        const groupCorrect = items.filter((item) => item.is_correct === true).length
        return <details className="result-group" key={key}>
          <summary>
            <span>{key === 'results' ? '答题明细' : sectionLabel(run.module, key)}</span>
            <small>{groupCorrect}/{items.length} 正确</small>
          </summary>
          <div className="result-rows">
            {items.map((item) => {
              const userAnswer = displayAnswer(item.user_answer)
              const correctAnswer = displayAnswer(item.correct_answer)
              const isCorrect = item.is_correct === true
              const status = isCorrect ? 'correct' : userAnswer ? 'incorrect' : 'unanswered'
              return <article key={String(item.question_id)} className={`result-row ${status}`}>
                <strong className="result-question-number">{String(item.question_number ?? item.question_id)}</strong>
                <div className="result-answer-pair">
                  <span><small>你的答案</small>{userAnswer || '未作答'}</span>
                  {!isCorrect && <span><small>正确答案</small>{correctAnswer || '—'}</span>}
                </div>
                <small className="result-evidence">{String(item.evidence_location ?? item.transcript_timestamp ?? item.explanation ?? '')}</small>
              </article>
            })}
          </div>
        </details>
      })}
    </div>
    <div className="result-actions"><Link className="button primary" to={`/feedback/${run.session_id}`}>查看复盘与正式记录</Link></div>
  </section>
}

function WritingScorePanel({ run }: { run: AssessmentRun }) {
  const queryClient = useQueryClient()
  return <section className="settings-section">
    <p className="eyebrow">Evidence-first review</p>
    <h2>Task 1 与 Task 2 双任务复评</h2>
    <p>Agent 必须分别提交两项任务的四项标准证据，Runtime 才按 Task 1:Task 2 = 1:2 汇总。若 Task 1 图片没有真实交付，系统会保留部分反馈，但拒绝生成完整总分。</p>
    <AgentPanel
      sessionId={run.session_id}
      contract="writing-mock-review@1"
      action="full_mock_review"
      onPersisted={() => void queryClient.invalidateQueries({ queryKey: ['assessment-run', run.run_id] })}
    />
  </section>
}

function SpeakingHandoffPanel({ run, onCreated }: { run: AssessmentRun; onCreated: () => void }) {
  const [packageText, setPackageText] = useState('')
  const create = useMutation({ mutationFn: () => api<{ prompt: string }>(`/api/v1/assessment-runs/${run.run_id}/speaking-handoff`, { method: 'POST', body: jsonBody({ mode: 'full_mock', provider: 'external_voice_live' }) }), onSuccess: (value) => { setPackageText(value.prompt); onCreated() } })
  return <article className="assessment-question-card"><p className="eyebrow">Voice / Live handoff</p><h2>将 Part 1–3 交给外部语音模型主持</h2><p>任务包会绑定当前 AssessmentRun 和 Session，并明确要求 11–14 分钟内不中途纠错。</p><button className="button primary" onClick={() => create.mutate()} disabled={create.isPending}>生成完整模考任务包</button>{packageText && <textarea readOnly value={packageText} aria-label="Speaking 完整模考任务包" />}{create.isError && <ErrorState error={create.error} />}</article>
}

function SpeakingReportPanel({ run }: { run: AssessmentRun }) {
  const queryClient = useQueryClient()
  const [report, setReport] = useState('')
  const imported = Boolean(
    (run.navigation.speaking_source_report as { status?: string } | undefined)?.status === 'imported',
  )
  const submit = useMutation({
    mutationFn: () => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(report) as Record<string, unknown>
      } catch {
        throw new Error('来源报告不是有效 JSON。')
      }
      return api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/speaking-report`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey() },
        body: jsonBody({
          provider: 'external_voice_live',
          mode: 'full_mock',
          report: parsed,
          expected_revision: undefined,
        }),
      })
    },
    onSuccess: (value) => queryClient.setQueryData(['assessment-run', run.run_id], value),
  })
  return <section className="settings-section">
    <p className="eyebrow">Voice evidence → local review</p>
    <h2>完整 Speaking Mock 复评</h2>
    <p>外部 Voice / Live 报告只作为来源证据，不会直接成为系统总分。导入后还需通过本地 Agent 契约复评；只有具备音频或语音模型直接观察时才允许 PRON 和完整总分。</p>
    {!imported
      ? <>
          <textarea value={report} onChange={(event) => setReport(event.target.value)} placeholder="粘贴结构化 JSON 报告" />
          <button className="button primary" disabled={!report.trim() || submit.isPending} onClick={() => submit.mutate()}>验证并绑定来源证据</button>
          {submit.isError && <ErrorState error={submit.error} />}
        </>
      : <>
          <StatusBadge tone="success">来源报告已绑定</StatusBadge>
          <AgentPanel
            sessionId={run.session_id}
            contract="speaking-evaluation@1"
            action="full_mock_re_evaluation"
            onPersisted={() => void queryClient.invalidateQueries({ queryKey: ['assessment-run', run.run_id] })}
          />
        </>}
  </section>
}

function ReviewedResult({ run }: { run: AssessmentRun }) {
  const band = run.score_result.band
  return <section className="assessment-result">
    <div className="result-hero">
      <CheckCircle2 />
      <div>
        <p className="eyebrow">Validated local result</p>
        <h2>{band === null || band === undefined ? '证据不足，未生成完整总分' : `IELTS training estimate ${String(band)}`}</h2>
        <p>结果来自经过 Schema、证据边界和 Runtime 聚合验证的正式 Session；它不是官方考官成绩。</p>
      </div>
    </div>
    <Link className="button primary" to={`/feedback/${run.session_id}`}>查看证据与正式记录</Link>
  </section>
}

async function saveNavigation(run: AssessmentRun, sectionKey: string, questionId: string) {
  try { await api(`/api/v1/assessment-runs/${run.run_id}/navigation`, { method: 'PUT', body: jsonBody({ navigation: { section_key: sectionKey, question_id: questionId } }) }) } catch { /* next server refresh reconciles navigation */ }
}
function questionSection(module: AssessmentRun['module'], question: Question) { return module === 'reading' ? String(question.passage_id) : module === 'writing' ? String(question.task) : `part-${String(question.part)}` }
function sectionLabel(module: string, key: string) { return module === 'reading' ? `Passage ${key.split('-').at(-1) ?? key}` : module === 'writing' ? key.toUpperCase() : key.replace('-', ' ') }
function displayedRemaining(run: AssessmentRun, clock: number) { void clock; if (run.timer.remaining_seconds === null) return null; const sync = new Date(run.timer.authoritative_at).getTime(); return Math.max(0, run.timer.remaining_seconds - (run.timer.running ? Math.floor((Date.now() - sync) / 1000) : 0)) }
function formatTime(seconds: number) { return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}` }
function hasAnswer(value?: { answer?: string | string[]; text?: string }) { const item = value?.text ?? value?.answer; return Array.isArray(item) ? item.some(Boolean) : Boolean(String(item ?? '').trim()) }
function readingParagraphs(value: string): Array<{ label?: string; text: string }> {
  return value.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean).map((item) => {
    const labelled = item.match(/^([A-I])\.\s+([\s\S]+)$/)
    return labelled ? { label: labelled[1], text: labelled[2].trim() } : { text: item }
  })
}
function normaliseOptions(question: Question) { const truth = question.question_type === 'true_false_not_given' ? ['TRUE', 'FALSE', 'NOT GIVEN'] : question.question_type === 'yes_no_not_given' ? ['YES', 'NO', 'NOT GIVEN'] : null; if (truth) return truth.map((key) => ({ key, text: key })); if (Array.isArray(question.options)) return question.options; return Object.entries(question.options ?? {}).map(([key, text]) => ({ key, text: String(text) })) }
function wordCount(value: string) { return value.trim() ? value.trim().split(/\s+/).length : 0 }
function displayAnswer(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(', ')
  if (value === null || value === undefined) return ''
  return String(value).trim()
}
