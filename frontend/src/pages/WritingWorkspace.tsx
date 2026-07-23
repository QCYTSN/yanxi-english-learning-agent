import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Send, TimerReset } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type Draft, type Question, type SessionSummary } from '../api/client'
import { AgentPanel } from '../components/AgentPanel'
import { ConformanceBadge, ErrorState, LoadingState, PageHeader, PhaseRail, SaveState, StructuredTaskVisual } from '../components/Common'

export function WritingWorkspace() {
  const { sessionId = '' } = useParams()
  const queryClient = useQueryClient()
  const session = useQuery({ queryKey: ['session', sessionId], queryFn: () => api<SessionSummary>(`/api/v1/sessions/${sessionId}`) })
  const question = useQuery({
    queryKey: ['question', session.data?.question_id],
    queryFn: () => api<Question>(`/api/v1/questions/${session.data?.question_id}`),
    enabled: Boolean(session.data?.question_id),
  })
  const draft = useQuery({ queryKey: ['draft', sessionId, 'writing'], queryFn: () => api<Draft>(`/api/v1/sessions/${sessionId}/draft/writing`) })
  const [content, setContent] = useState('')
  const [draftRevision, setDraftRevision] = useState(0)
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const initialized = useRef(false)
  const lastSaved = useRef('')

  useEffect(() => {
    if (!draft.data || initialized.current) return
    const savedContent = String(draft.data.payload.content ?? '')
    setContent(savedContent)
    setDraftRevision(draft.data.revision)
    lastSaved.current = savedContent
    initialized.current = true
    setSaveState(draft.data.updated_at ? 'saved' : 'idle')
  }, [draft.data])

  useEffect(() => {
    if (!initialized.current || content === lastSaved.current) return
    setSaveState('saving')
    const timer = window.setTimeout(async () => {
      try {
        const saved = await api<Draft>(`/api/v1/sessions/${sessionId}/draft`, {
          method: 'PUT',
          body: jsonBody({ draft_kind: 'writing', expected_revision: draftRevision, payload: { content } }),
        })
        setDraftRevision(saved.revision)
        lastSaved.current = content
        setSaveState('saved')
      } catch {
        setSaveState('error')
      }
    }, 850)
    return () => window.clearTimeout(timer)
  }, [content, draftRevision, sessionId])

  const submit = useMutation({
    mutationFn: () => {
      const versions = (session.data?.versions as Array<{ label: string }> | undefined) ?? []
      const label = versions.some((item) => item.label === 'v1') ? 'v2' : 'v1'
      return api<SessionSummary>(`/api/v1/writing/${sessionId}/versions`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey() },
        body: jsonBody({ label, content, expected_revision: session.data?.revision ?? 0 }),
      })
    },
    onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ['session', sessionId] }) },
  })
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ['session', sessionId] })

  if (session.isPending || draft.isPending) return <LoadingState />
  if (session.isError) return <ErrorState error={session.error} />
  const status = session.data.status
  const versions = (session.data.versions as Array<{ label: string; content: string }> | undefined) ?? []
  const nextLabel = versions.some((item) => item.label === 'v1') ? 'V2' : 'V1'
  const submittedLabel = versions.at(-1)?.label
  const isTask1 = question.data?.task === 'task1'
  const minimumWords = Number(question.data?.minimum_words ?? (isTask1 ? 150 : 250))
  const words = wordCount(content)
  const minutes = isTask1 ? 20 : 40
  return (
    <div className="workspace-page">
      <PageHeader eyebrow={sessionId} title="Writing 工作区" description="先完成自己的版本，再查看证据化反馈。Task 2 在完整考试中按双倍权重计分。" action={<div className="header-badges"><ConformanceBadge status={question.data?.conformance_status ?? String(session.data.conformance_status ?? '')} mode={question.data?.practice_mode ?? String(session.data.practice_mode ?? '')} /><SaveState state={saveState} /></div>} />
      <PhaseRail active={status === 'awaiting_revision' ? '修改' : status === 'awaiting_feedback' ? '反馈' : '写作'} phases={['审题', '写作', '反馈', '修改', '完成']} />
      <div className="writing-grid">
        <aside className="task-panel">
          <p className="eyebrow">Task</p>
          <h2>{question.data?.task === 'task1' ? 'Academic Task 1' : 'Academic Task 2'}</h2>
          <p className="task-prompt">{question.data?.content ?? '题目正在载入。'}</p>
          {question.data?.task_data && <StructuredTaskVisual data={question.data.task_data} />}
          {question.data?.task === 'task1' && <MediaUpload sessionId={sessionId} />}
        </aside>
        <section className="editor-panel">
          <div className="editor-toolbar"><span>{nextLabel}</span><span className={words < minimumWords ? 'word-count-warning' : undefined}>{words} / 至少 {minimumWords} words</span><span><TimerReset size={16} />{minutes}:00</span></div>
          <label className="sr-only" htmlFor="essay-editor">作文内容</label>
          <textarea id="essay-editor" className="essay-editor" value={content} onChange={(event) => setContent(event.target.value)} placeholder="在这里开始写作……" spellCheck />
          <div className="editor-footer"><SaveState state={saveState} /><button className="button primary" onClick={() => submit.mutate()} disabled={!content.trim() || submit.isPending || status === 'awaiting_feedback'}><Send size={18} />提交 {nextLabel}</button></div>
          {submit.isError && <ErrorState error={submit.error} />}
        </section>
      </div>
      {status === 'awaiting_feedback' && <AgentPanel sessionId={sessionId} contract="writing-review@1" action={submittedLabel === 'v1' ? 'first_review' : 'version_comparison'} onPersisted={refresh} />}
      {status === 'awaiting_revision' && <div className="next-step-card"><div><h2>反馈已保存</h2><p>先查看证据和三个重点，再完成自己的修改。</p></div><Link className="button primary" to={`/feedback/${sessionId}`}>查看反馈</Link></div>}
    </div>
  )
}

function wordCount(value: string) { return value.trim() ? value.trim().split(/\s+/).length : 0 }

function MediaUpload({ sessionId }: { sessionId: string }) {
  const [asset, setAsset] = useState<{ media_id: string; alt_text: string } | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData()
      form.append('image', file)
      form.append('alt_text', 'Learner-provided IELTS Task 1 visual')
      form.append('owner_type', 'session')
      form.append('owner_id', sessionId)
      return api<{ media_id: string; alt_text: string }>('/api/v1/media', { method: 'POST', body: form })
    },
    onSuccess: (value) => {
      setAsset(value)
      setPreview(`/api/v1/media/${value.media_id}/content`)
    },
  })
  return (
    <div className="media-upload">
      {preview ? <a className="media-preview" href={preview} target="_blank" rel="noreferrer" aria-label="在新窗口查看 Task 1 原图"><img src={preview} alt={asset?.alt_text ?? 'Task 1 visual'} /></a> : <div className="media-placeholder"><ImagePlus aria-hidden="true" /><span>可以登记一张本地 Task 1 图片</span></div>}
      <label className="button secondary">选择图片<input className="sr-only" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) upload.mutate(file) }} /></label>
      {upload.isError && <ErrorState error={upload.error} />}
    </div>
  )
}
