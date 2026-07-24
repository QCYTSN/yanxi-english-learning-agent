import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark, CheckCircle2, Headphones, Send, TimerReset, Volume2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type AssessmentRun, type Question } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge, StructuredTaskVisual } from '../components/Common'

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
    {value.status === 'completed' && value.module !== 'writing' && value.module !== 'speaking'
      ? <ObjectiveResult run={value} />
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
    return <article className="assessment-context passage-panel"><p className="eyebrow">{sectionKey}</p><h2>{passage?.title ?? 'Reading passage'}</h2><div className="passage-text">{paragraphs(passage?.body ?? '').map((item, index) => <p key={index}><span className="paragraph-label">{String.fromCharCode(65 + index)}</span>{item}</p>)}</div></article>
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
  return <article className="assessment-question-card">
    <div className="question-meta"><span>Question {question.question_number ?? question.question_id}</span><button disabled={disabled || save.isPending} className={flagged ? 'flag-button active' : 'flag-button'} onClick={() => { const next = !flagged; setFlagged(next); save.mutate({ flagged: next }) }}><Bookmark size={16} />{flagged ? '已标记' : '稍后检查'}</button></div>
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
            }} /><span><b>{option.key}</b>{option.text}</span></label>
          })}</div>
        : <div className="answer-entry"><input value={String(answer)} onChange={(event) => setAnswer(event.target.value)} onBlur={() => save.mutate(undefined)} disabled={disabled} placeholder={question.answer_constraints?.word_limit ? `不超过 ${question.answer_constraints.word_limit} 个词` : '输入答案'} /><button className="button secondary" onClick={() => save.mutate(undefined)} disabled={disabled || save.isPending}>保存</button></div>}
    {save.isError && <ErrorState error={save.error} />}
  </article>
}

function AudioPanel({ run, mediaId }: { run: AssessmentRun; mediaId: string }) {
  const queryClient = useQueryClient()
  const audioRef = useRef<HTMLAudioElement>(null)
  const state = run.media_state[mediaId] ?? {}
  const start = useMutation({
    mutationFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}/start`, { method: 'POST' }),
    onSuccess: (value) => queryClient.setQueryData(['assessment-run', run.run_id], value),
  })
  const lastSent = useRef(Number(state.position_seconds ?? 0))
  function update(completed = false) {
    const position = audioRef.current?.currentTime ?? lastSent.current
    if (!completed && position - lastSent.current < 5) return
    lastSent.current = position
    void api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}`, { method: 'PUT', body: jsonBody({ position_seconds: position, completed }) })
      .then((value) => queryClient.setQueryData(['assessment-run', run.run_id], value))
  }
  return <article className="assessment-context audio-runner"><Headphones size={28} /><p className="eyebrow">一次播放</p><h2>Listening audio</h2><p>刷新页面不会重置播放次数或已记录进度。开始后请保持此页面打开。</p>
    {!state.play_count ? <button className="button primary" disabled={!mediaId || start.isPending} onClick={() => start.mutate()}><Volume2 size={18} />开始唯一一次播放</button> : <audio ref={audioRef} src={`/api/v1/assessment-runs/${run.run_id}/audio/${mediaId}/content`} controls={!state.completed} autoPlay onLoadedMetadata={(event) => { event.currentTarget.currentTime = Number(state.position_seconds ?? 0) }} onTimeUpdate={() => update(false)} onEnded={() => update(true)} onSeeking={(event) => { if (event.currentTarget.currentTime + 0.5 < Number(state.position_seconds ?? 0)) event.currentTarget.currentTime = Number(state.position_seconds ?? 0) }} />}
    {state.completed && <StatusBadge tone="success">播放已完成</StatusBadge>}{start.isError && <ErrorState error={start.error} />}
  </article>
}

function ObjectiveResult({ run }: { run: AssessmentRun }) {
  const results = Array.isArray(run.score_result.question_results) ? run.score_result.question_results as Array<Record<string, unknown>> : []
  return <section className="assessment-result"><div className="result-hero"><CheckCircle2 /><div><p className="eyebrow">Submitted</p><h2>{String(run.score_result.raw_score ?? 0)} / {String(run.score_result.total ?? results.length)}</h2><p>{run.score_result.band ? `IELTS training estimate ${String(run.score_result.band)}` : '已保存原始分；套题没有经审核的换算表，因此不生成 Band。'}</p></div></div><div className="result-list">{results.map((item) => <article key={String(item.question_id)} className={item.is_correct ? 'correct' : 'incorrect'}><strong>{String(item.question_number ?? item.question_id)}</strong><div><p>你的答案：{String(item.user_answer ?? '未作答')}</p><p>正确答案：{String(item.correct_answer ?? '')}</p><small>{String(item.evidence_location ?? item.transcript_timestamp ?? item.explanation ?? '')}</small></div></article>)}</div><Link className="button primary" to={`/feedback/${run.session_id}`}>查看正式 Session</Link></section>
}

function WritingScorePanel({ run }: { run: AssessmentRun }) {
  const queryClient = useQueryClient()
  const [scores, setScores] = useState<Record<string, string>>({ TA: '', TR: '', CC1: '', LR1: '', GRA1: '', CC2: '', LR2: '', GRA2: '' })
  const [task1Evidence, setTask1Evidence] = useState('')
  const [task2Evidence, setTask2Evidence] = useState('')
  const [evaluator, setEvaluator] = useState('')
  const scoreKeys = ['TA', 'TR', 'CC1', 'LR1', 'GRA1', 'CC2', 'LR2', 'GRA2']
  const complete = Boolean(scoreKeys.every((key) => scores[key] !== '') && task1Evidence.trim() && task2Evidence.trim() && evaluator.trim())
  const save = useMutation({
    mutationFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/writing-score`, { method: 'POST', body: jsonBody({
      task1: { criteria: { TA: Number(scores.TA), CC: Number(scores.CC1), LR: Number(scores.LR1), GRA: Number(scores.GRA1) }, evidence: [task1Evidence], confidence: 'medium', evaluator_model: evaluator, calibration_status: 'unknown', rubric_version: 'IELTS Writing descriptors' },
      task2: { criteria: { TR: Number(scores.TR), CC: Number(scores.CC2), LR: Number(scores.LR2), GRA: Number(scores.GRA2) }, evidence: [task2Evidence], confidence: 'medium', evaluator_model: evaluator, calibration_status: 'unknown', rubric_version: 'IELTS Writing descriptors' },
    }) }),
    onSuccess: (value) => queryClient.setQueryData(['assessment-run', run.run_id], value),
  })
  return <section className="settings-section"><p className="eyebrow">Validated evaluator import</p><h2>Task 1 与 Task 2 分项复评</h2><p>这里不再预填 6 分，也不是学习者自评。请从真实 Agent 或人工 IELTS 评阅结果逐项导入；Runtime 负责校验并按 1:2 汇总。</p><label>评阅来源 / 模型<input value={evaluator} onChange={(event) => setEvaluator(event.target.value)} placeholder="例如 Claude Code · 实际模型名，或人工评阅者" /></label><div className="score-grid compact">{scoreKeys.map((key) => <label key={key}>{key}<select value={scores[key]} onChange={(event) => setScores({ ...scores, [key]: event.target.value })}><option value="">未评分</option>{Array.from({ length: 19 }, (_, index) => index * 0.5).map((value) => <option key={value} value={value}>{value.toFixed(1)}</option>)}</select></label>)}</div><label>Task 1 评分证据<textarea value={task1Evidence} onChange={(event) => setTask1Evidence(event.target.value)} placeholder="引用原文并说明 TA / CC / LR / GRA 判断依据" /></label><label>Task 2 评分证据<textarea value={task2Evidence} onChange={(event) => setTask2Evidence(event.target.value)} placeholder="引用原文并说明 TR / CC / LR / GRA 判断依据" /></label><button className="button primary" disabled={!complete || save.isPending} onClick={() => save.mutate()}>验证复评并按 1:2 汇总</button>{save.isError && <ErrorState error={save.error} />}</section>
}

function SpeakingHandoffPanel({ run, onCreated }: { run: AssessmentRun; onCreated: () => void }) {
  const [packageText, setPackageText] = useState('')
  const create = useMutation({ mutationFn: () => api<{ prompt: string }>(`/api/v1/assessment-runs/${run.run_id}/speaking-handoff`, { method: 'POST', body: jsonBody({ mode: 'full_mock', provider: 'external_voice_live' }) }), onSuccess: (value) => { setPackageText(value.prompt); onCreated() } })
  return <article className="assessment-question-card"><p className="eyebrow">Voice / Live handoff</p><h2>将 Part 1–3 交给外部语音模型主持</h2><p>任务包会绑定当前 AssessmentRun 和 Session，并明确要求 11–14 分钟内不中途纠错。</p><button className="button primary" onClick={() => create.mutate()} disabled={create.isPending}>生成完整模考任务包</button>{packageText && <textarea readOnly value={packageText} aria-label="Speaking 完整模考任务包" />}{create.isError && <ErrorState error={create.error} />}</article>
}

function SpeakingReportPanel({ run }: { run: AssessmentRun }) {
  const queryClient = useQueryClient()
  const [report, setReport] = useState('')
  const submit = useMutation({ mutationFn: () => api<AssessmentRun>(`/api/v1/assessment-runs/${run.run_id}/speaking-report`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() }, body: jsonBody({ provider: 'external_voice_live', mode: 'full_mock', report: JSON.parse(report), expected_revision: undefined }) }), onSuccess: (value) => queryClient.setQueryData(['assessment-run', run.run_id], value) })
  return <section className="settings-section"><p className="eyebrow">Report import</p><h2>导回外部 Voice / Live 报告</h2><p>外部分数不会直接冒充本地复评；只有文字时 Pronunciation 会明确标记证据不足。</p><textarea value={report} onChange={(event) => setReport(event.target.value)} placeholder='粘贴结构化 JSON 报告' /><button className="button primary" disabled={!report.trim() || submit.isPending} onClick={() => submit.mutate()}>验证并绑定到当前运行</button>{submit.isError && <ErrorState error={submit.error} />}</section>
}

async function saveNavigation(run: AssessmentRun, sectionKey: string, questionId: string) {
  try { await api(`/api/v1/assessment-runs/${run.run_id}/navigation`, { method: 'PUT', body: jsonBody({ navigation: { section_key: sectionKey, question_id: questionId } }) }) } catch { /* next server refresh reconciles navigation */ }
}
function questionSection(module: AssessmentRun['module'], question: Question) { return module === 'reading' ? String(question.passage_id) : module === 'writing' ? String(question.task) : `part-${String(question.part)}` }
function sectionLabel(module: string, key: string) { return module === 'reading' ? `Passage ${key.split('-').at(-1) ?? key}` : module === 'writing' ? key.toUpperCase() : key.replace('-', ' ') }
function displayedRemaining(run: AssessmentRun, clock: number) { void clock; if (run.timer.remaining_seconds === null) return null; const sync = new Date(run.timer.authoritative_at).getTime(); return Math.max(0, run.timer.remaining_seconds - (run.timer.running ? Math.floor((Date.now() - sync) / 1000) : 0)) }
function formatTime(seconds: number) { return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}` }
function hasAnswer(value?: { answer?: string | string[]; text?: string }) { const item = value?.text ?? value?.answer; return Array.isArray(item) ? item.some(Boolean) : Boolean(String(item ?? '').trim()) }
function paragraphs(value: string) { return value.split(/\n\s*\n/).map((item) => item.trim()).filter(Boolean) }
function normaliseOptions(question: Question) { const truth = question.question_type === 'true_false_not_given' ? ['TRUE', 'FALSE', 'NOT GIVEN'] : question.question_type === 'yes_no_not_given' ? ['YES', 'NO', 'NOT GIVEN'] : null; if (truth) return truth.map((key) => ({ key, text: key })); if (Array.isArray(question.options)) return question.options; return Object.entries(question.options ?? {}).map(([key, text]) => ({ key, text: String(text) })) }
function wordCount(value: string) { return value.trim() ? value.trim().split(/\s+/).length : 0 }
