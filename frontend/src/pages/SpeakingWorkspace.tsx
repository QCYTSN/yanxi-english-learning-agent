import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Clipboard, ExternalLink, Mic2, Plus, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type SessionSummary } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { ConformanceBadge, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

type HandoffQuestion = { question_id: string; part: number | string; topic?: string; content: string }
type Handoff = {
  provider: string
  mode: string
  practice_mode?: string
  conformance_status?: string
  conformance_report?: { errors?: string[]; warnings?: string[] }
  prompt: string
  questions: HandoffQuestion[]
}
type SpeakingReport = {
  source_observations?: { transcript?: string; evidence_types?: string[]; pronunciation_observations?: unknown[] }
  source_model_estimate?: { estimated_overall?: number; confidence?: string }
  local_evaluation?: { status?: string; estimated_overall?: number; confidence?: string; notes?: string }
}
type SpeakingSession = SessionSummary & { speaking_handoff?: Handoff; speaking_report?: SpeakingReport }
type Story = { story_id: string; title: string; events: string[]; usable_topics: string[]; expressions?: string[] }
type SpeakingMode = 'full_mock' | 'part1' | 'part2' | 'part3'

export function SpeakingWorkspace() {
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('session')
  const practiceUnitId = params.get('practice_unit_id')
  const requestedMode = params.get('mode')
  const initialMode: SpeakingMode = ['part1', 'part2', 'part3'].includes(requestedMode ?? '')
    ? requestedMode as SpeakingMode
    : 'full_mock'
  const requestedQuestionIds = (params.get('question_ids') ?? '').split(',').filter(Boolean)
  const [mode, setMode] = useState<SpeakingMode>(initialMode)
  const [provider, setProvider] = useState('ChatGPT Voice / Live')
  const [session, setSession] = useState<SpeakingSession | null>(null)
  const [copied, setCopied] = useState(false)
  const [importKind, setImportKind] = useState<'transcript' | 'json'>('transcript')
  const [reportText, setReportText] = useState('')
  const queryClient = useQueryClient()
  const existing = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => api<SpeakingSession>(`/api/v1/sessions/${sessionId}`),
    enabled: Boolean(sessionId),
  })
  const active = session ?? existing.data ?? null
  const stories = useQuery({ queryKey: ['speaking-stories'], queryFn: () => api<Story[]>('/api/v1/speaking/stories') })
  const handoff = useMutation({
    mutationFn: () => api<SpeakingSession>('/api/v1/speaking/handoffs', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({
        mode,
        provider,
        question_ids: requestedQuestionIds.length ? requestedQuestionIds : null,
        practice_unit_id: practiceUnitId,
      }),
    }),
    onSuccess: (value) => {
      setSession(value)
      setParams({ session: value.session_id })
    },
  })
  const importReport = useMutation({
    mutationFn: () => {
      if (!active) throw new Error('请先生成一次 Speaking 任务包')
      const body = importKind === 'json'
        ? { provider, mode: active.mode ?? mode, report: JSON.parse(reportText) as Record<string, unknown>, expected_revision: active.revision ?? 0 }
        : { provider, mode: active.mode ?? mode, transcript: reportText, expected_revision: active.revision ?? 0 }
      return api<SpeakingSession>(`/api/v1/speaking/${active.session_id}/reports`, { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() }, body: jsonBody(body) })
    },
    onSuccess: (value) => {
      setSession(value)
      void queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })
  const packageData = active?.speaking_handoff

  return (
    <div className="page">
      <PageHeader
        eyebrow="Speaking · external handoff"
        title="把口语流程交给 Voice / Live 主持"
        description="本地系统负责选题、规则、记录和复盘；外部语音页面负责对话。两边不假装存在自动连接。"
        action={active ? <StatusBadge tone={active.status === 'completed' ? 'success' : 'warning'}>{active.status}</StatusBadge> : undefined}
      />
      {existing.isPending && sessionId && <LoadingState />}
      {existing.isError && <ErrorState error={existing.error} />}
      <section className="speaking-boundary">
        <ShieldCheck aria-hidden="true" />
        <div><strong>计时属于外部主持方</strong><p>任务包会要求 Part 2 准备 1 分钟、作答最多 2 分钟；如果 Voice/Live 无法可靠计时，它必须明确说明。</p></div>
      </section>

      {!packageData && (
        <section className="settings-section">
          <h2>生成语音练习任务包</h2>
          <div className="handoff-options">
            <label>练习模式<select value={mode} onChange={(event) => setMode(event.target.value as SpeakingMode)}><option value="full_mock">完整 Part 1–3 流程</option><option value="part1">Part 1 日常问答</option><option value="part2">Part 2 个人陈述</option><option value="part3">Part 3 深入讨论</option></select></label>
            <label>外部主持方<input value={provider} onChange={(event) => setProvider(event.target.value)} /></label>
          </div>
          <button className="button primary" onClick={() => handoff.mutate()} disabled={handoff.isPending}><Mic2 size={18} />生成任务包</button>
          {handoff.isError && <ErrorState error={handoff.error} />}
        </section>
      )}

      {packageData && (
        <>
          <div className="speaking-grid">
            <section className="settings-section">
              <p className="eyebrow">Question set</p>
              <h2>{packageData.mode.startsWith('part') ? `${packageData.mode.replace('part', 'Part ')} 专项` : packageData.conformance_status === 'verified' ? '完整 IELTS Speaking 模考' : '完整 Speaking 流程练习'}</h2>
              <ConformanceBadge status={packageData.conformance_status} mode={packageData.practice_mode} />
              {packageData.conformance_status !== 'verified' && <p className="conformance-note">题目流程符合 Part 1–3 结构，但题库尚未全部完成人工复核，因此不会换算正式 Band。</p>}
              <div className="speaking-question-list">{packageData.questions.map((question) => <article key={question.question_id}><span>Part {question.part}</span><p>{question.content}</p></article>)}</div>
            </section>
            <section className="settings-section">
              <p className="eyebrow">Handoff package</p>
              <h2>复制给外部 Voice / Live</h2>
              <textarea className="handoff-prompt" readOnly value={packageData.prompt} aria-label="Speaking Voice Live 任务包" />
              <div className="row-actions">
                <button className="button secondary" onClick={() => { void navigator.clipboard.writeText(packageData.prompt); setCopied(true) }}><Clipboard size={17} />{copied ? '已复制' : '复制任务包'}</button>
                <a className="button primary" href="https://chatgpt.com/" target="_blank" rel="noreferrer">打开外部语音页面<ExternalLink size={17} /></a>
              </div>
            </section>
          </div>
          <section className="settings-section report-import">
            <div className="section-heading"><div><p className="eyebrow">Return</p><h2>导回转写或结构化报告</h2></div></div>
            <div className="segmented" role="group" aria-label="Speaking 导入格式"><button className={importKind === 'transcript' ? 'active' : ''} onClick={() => setImportKind('transcript')}>转写文本</button><button className={importKind === 'json' ? 'active' : ''} onClick={() => setImportKind('json')}>结构化 JSON</button></div>
            <label><span>{importKind === 'json' ? 'Voice/Live 输出的报告 JSON' : '完整转写文本'}</span><textarea value={reportText} onChange={(event) => setReportText(event.target.value)} placeholder={importKind === 'json' ? '{ "mode": "full_mock", ... }' : '粘贴外部语音练习的转写……'} /></label>
            <button className="button primary" disabled={!reportText.trim() || importReport.isPending} onClick={() => importReport.mutate()}>验证并保存报告</button>
            {importReport.isError && <ErrorState error={importReport.error} />}
          </section>
        </>
      )}

      {active?.speaking_report && <SpeakingReportView report={active.speaking_report} />}
      {active?.status === 'awaiting_feedback' && <AgentPanel
        sessionId={active.session_id}
        contract="speaking-evaluation@1"
        action="transcript_review"
        onPersisted={() => {
          setSession(null)
          void queryClient.invalidateQueries({ queryKey: ['session', active.session_id] })
        }}
      />}
      <StoryBank stories={stories.data ?? []} pending={stories.isPending} error={stories.error} />
    </div>
  )
}

function SpeakingReportView({ report }: { report: SpeakingReport }) {
  const evidence = report.source_observations?.evidence_types ?? []
  const local = report.local_evaluation ?? {}
  return <section className="settings-section speaking-report"><p className="eyebrow">Evidence boundary</p><h2>本次导入结果</h2><div className="report-facts"><span>证据 <strong>{evidence.join(' / ') || '未声明'}</strong></span><span>本地复评 <strong>{local.status ?? 'pending'}</strong></span><span>估分 <strong>{local.estimated_overall ?? '证据不足'}</strong></span></div><p>{evidence.some((item) => item === 'audio' || item === 'voice_model_observation') ? '报告包含语音观察，但仍会区分来源模型和本地复评。' : '当前只有文字证据，不生成可信的 Pronunciation 数字分数。'}</p>{report.source_observations?.transcript && <details><summary>查看转写</summary><p className="transcript-text">{report.source_observations.transcript}</p></details>}</section>
}

function StoryBank({ stories, pending, error }: { stories: Story[]; pending: boolean; error: unknown }) {
  const queryClient = useQueryClient()
  const [title, setTitle] = useState('')
  const [event, setEvent] = useState('')
  const [topics, setTopics] = useState('')
  const slug = useMemo(() => title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50), [title])
  const create = useMutation({
    mutationFn: () => api<Story>('/api/v1/speaking/stories', { method: 'POST', body: jsonBody({ story_id: slug || `story-${Date.now()}`, title, events: [event], usable_topics: topics.split(',').map((item) => item.trim()).filter(Boolean) }) }),
    onSuccess: () => { setTitle(''); setEvent(''); setTopics(''); void queryClient.invalidateQueries({ queryKey: ['speaking-stories'] }) },
  })
  return <section className="settings-section story-bank"><div className="section-heading"><div><p className="eyebrow">Story Bank</p><h2>可复用个人素材</h2></div></div>{pending && <LoadingState />}{Boolean(error) && <ErrorState error={error} />}<div className="story-grid">{stories.map((story) => <article key={story.story_id}><strong>{story.title}</strong><p>{story.events[0]}</p><span>{story.usable_topics.join(' · ')}</span></article>)}</div><details><summary><Plus size={16} />添加一条素材</summary><div className="story-form"><label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>关键事件<textarea value={event} onChange={(event_) => setEvent(event_.target.value)} /></label><label>适用话题（逗号分隔）<input value={topics} onChange={(event_) => setTopics(event_.target.value)} /></label><button className="button secondary" disabled={!title || !event || !topics || create.isPending} onClick={() => create.mutate()}>保存素材</button>{create.isError && <ErrorState error={create.error} />}</div></details></section>
}
