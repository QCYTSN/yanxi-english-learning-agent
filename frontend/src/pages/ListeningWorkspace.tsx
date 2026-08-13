import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Headphones, Play, RotateCcw, Volume2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type SessionSummary } from '../api/client'
import { ConformanceBadge, EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type Category = { category: string; label: string; total: number; due: number; mastered: number }
type Progress = { attempts: number; correct: number; incorrect: number; mastery: number; due: boolean }
type ListeningItem = { item_id: string; category: string; category_label: string; expression: string; meaning_zh: string; pronunciation_note?: string; collocations?: string[]; synonyms?: string[]; distractors?: string[]; spelling_risk?: string; example?: string; progress: Progress }
type AttemptResponse = { session: SessionSummary; attempt: { is_correct: boolean; user_answer: string; correct_answer: string; error_tags: string[] }; item: ListeningItem }

export function ListeningWorkspace() {
  const { sessionId } = useParams()
  const [searchParams] = useSearchParams()
  const practiceUnitId = searchParams.get('practice_unit_id')
  const requestedItemId = searchParams.get('item')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [category, setCategory] = useState('')
  const [index, setIndex] = useState(0)
  const [answer, setAnswer] = useState('')
  const [errorTag, setErrorTag] = useState('')
  const [feedback, setFeedback] = useState<AttemptResponse | null>(null)
  const speechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window
  const sessionQuery = useQuery({ queryKey: ['session', sessionId], queryFn: () => api<SessionSummary>(`/api/v1/sessions/${sessionId}`), enabled: Boolean(sessionId) })
  const [session, setSession] = useState<SessionSummary | null>(null)
  useEffect(() => { if (sessionQuery.data) setSession(sessionQuery.data) }, [sessionQuery.data])
  const categories = useQuery({ queryKey: ['listening-categories'], queryFn: () => api<Category[]>('/api/v1/listening/categories') })
  const items = useQuery({ queryKey: ['listening-items', category], queryFn: () => api<ListeningItem[]>(`/api/v1/listening/items?limit=200${category ? `&category=${encodeURIComponent(category)}` : ''}`) })
  useEffect(() => {
    if (!requestedItemId || !items.data) return
    const requestedIndex = items.data.findIndex((item) => item.item_id === requestedItemId)
    if (requestedIndex >= 0) setIndex(requestedIndex)
  }, [items.data, requestedItemId])
  const current = items.data?.[index % Math.max(items.data.length, 1)]
  const create = useMutation({
    mutationFn: () => api<SessionSummary>('/api/v1/sessions', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() }, body: jsonBody({ module: 'listening', mode: 'high-frequency-drill', source_id: 'starter-high-frequency', practice_unit_id: practiceUnitId }) }),
    onSuccess: (value) => { setSession(value); navigate(`/practice/listening/${value.session_id}`, { replace: true }) },
  })
  const attempt = useMutation({
    mutationFn: () => {
      if (!session || !current) throw new Error('练习尚未准备好')
      return api<AttemptResponse>(`/api/v1/listening/${session.session_id}/attempts`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() }, body: jsonBody({ item_id: current.item_id, user_answer: answer, error_tags: errorTag ? [errorTag] : [], expected_revision: session.revision ?? 0 }) })
    },
    onSuccess: (value) => {
      setFeedback(value)
      setSession(value.session)
      void queryClient.invalidateQueries({ queryKey: ['listening-categories'] })
      void queryClient.invalidateQueries({ queryKey: ['listening-items'] })
    },
  })
  const finish = useMutation({
    mutationFn: () => api<SessionSummary>(`/api/v1/sessions/${session?.session_id}/finish`, { method: 'POST' }),
    onSuccess: () => navigate('/history'),
  })
  const totals = useMemo(() => categories.data?.reduce((sum, item) => sum + item.total, 0) ?? 0, [categories.data])

  function playExpression() {
    if (!current || !speechSupported) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(current.expression)
    utterance.lang = 'en-GB'
    utterance.rate = 0.88
    window.speechSynthesis.speak(utterance)
  }

  function next() {
    setFeedback(null); setAnswer(''); setErrorTag(''); setIndex((value) => value + 1)
  }

  return <div className="page listening-workspace-page">
    <PageHeader eyebrow="Listening · high-frequency corpus" title="高频场景听辨" description="听写训练使用系统语音，只用于练习，不冒充真实考试录音。" action={<div className="header-badges"><ConformanceBadge status="skill_only" mode="skill_drill" />{session && <button className="button secondary" onClick={() => finish.mutate()} disabled={finish.isPending}><CheckCircle2 size={17} />结束本轮</button>}</div>} />
    {sessionQuery.isError && <ErrorState error={sessionQuery.error} />}
    {!session && <section className="primary-card"><div><StatusBadge>{totals} 条原创表达</StatusBadge><h2>建立一次 Listening 高频训练 Session</h2><p>每次听写会记录正确率、错因和复习状态。</p></div>{totals > 0 ? <button className="button primary" onClick={() => create.mutate()} disabled={create.isPending}><Headphones size={18} />开始训练</button> : <div className="empty-state"><p>本机还没有听力素材</p><p className="muted">可以在内容工作台导入自有材料，或先到「学习对话」里练听力理解。</p></div>}</section>}
    {create.isError && <ErrorState error={create.error} />}
    {finish.isError && <ErrorState error={finish.error} />}
    <div className="listening-layout">
      <aside className="listening-categories"><button className={!category ? 'active' : ''} onClick={() => { setCategory(''); setIndex(0); setFeedback(null) }}><span>全部场景</span><strong>{totals}</strong></button>{categories.data?.map((item) => <button key={item.category} className={category === item.category ? 'active' : ''} onClick={() => { setCategory(item.category); setIndex(0); setFeedback(null) }}><span>{item.label}<small>{item.due} 待复习 · {item.mastered} 已掌握</small></span><strong>{item.total}</strong></button>)}</aside>
      <section className="listening-drill">
        {items.isPending && <LoadingState />}{items.isError && <ErrorState error={items.error} />}
        {items.isSuccess && !items.data?.length && !current && <EmptyState title="暂无听力表达可练习"><p className="muted">导入材料后，这里会出现可听写的表达和复习进度。</p></EmptyState>}
        {current && <><div className="drill-heading"><div><p className="eyebrow">{current.category_label}</p><h2>{feedback ? current.expression : '播放并写下你听到的表达'}</h2></div><StatusBadge>掌握度 {current.progress.mastery}/5</StatusBadge></div><button className="listen-button" onClick={playExpression} disabled={!speechSupported}><Volume2 size={27} /><span>{speechSupported ? '播放英式系统语音' : '当前浏览器不支持系统语音'}</span></button>{!speechSupported && <p className="muted">请使用 Edge 或 Chrome 打开本地学习桌面后再进行听写。</p>}<label className="listening-answer">你的答案<input value={answer} disabled={Boolean(feedback)} onChange={(event) => setAnswer(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && answer.trim() && session && !feedback) attempt.mutate() }} /></label><label className="listening-error-reason">可能的困难<select value={errorTag} disabled={Boolean(feedback)} onChange={(event) => setErrorTag(event.target.value)}><option value="">暂不标记</option><option value="not_heard">没有听清</option><option value="spelling">拼写错误</option><option value="segmentation">分词/连读</option><option value="distractor">易混表达</option></select></label>{!feedback ? <button className="button primary" disabled={!session || !answer.trim() || attempt.isPending} onClick={() => attempt.mutate()}><Play size={17} />提交听写</button> : <div className={`listening-feedback ${feedback.attempt.is_correct ? 'correct' : 'incorrect'}`}><h3>{feedback.attempt.is_correct ? '听写正确' : `正确表达：${current.expression}`}</h3><p>{current.meaning_zh}</p>{current.pronunciation_note && <p><strong>听辨：</strong>{current.pronunciation_note}</p>}{current.collocations?.length ? <p><strong>搭配：</strong>{current.collocations.join('；')}</p> : null}{current.distractors?.length ? <p><strong>易混：</strong>{current.distractors.join('；')}</p> : null}<button className="button secondary" onClick={next}><RotateCcw size={17} />下一条</button></div>}{attempt.isError && <ErrorState error={attempt.error} />}</>}
      </section>
    </div>
    <section className="settings-section listening-library"><div className="section-heading"><div><p className="eyebrow">Browse</p><h2>当前场景表达</h2></div></div><div className="table-scroll" tabIndex={0}><table><thead><tr><th>表达</th><th>中文</th><th>掌握度</th></tr></thead><tbody>{items.data?.map((item) => <tr key={item.item_id}><td>{item.expression}</td><td>{item.meaning_zh}</td><td>{item.progress.mastery}/5</td></tr>)}</tbody></table></div></section>
  </div>
}
