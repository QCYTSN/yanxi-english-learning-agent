import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  BookOpenCheck,
  ChevronDown,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  Paperclip,
  Sparkles,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  jsonBody,
  type AgentRun,
  type ModelProvider,
  type StudyHelpResult,
  type StudyThread,
  type TutorProposal,
} from '../api/client'
import { ErrorState, LoadingState, StatusBadge } from '../components/Common'
import { MaterialComposer } from '../components/MaterialComposer'
import { ThreadActions } from '../components/ThreadActions'
import { addStudyMessage, requestRemoteProcessingConsent, startStudyHelpRun } from '../studyThreads'

const terminalRunStates = new Set([
  'persisted',
  'failed',
  'cancelled',
  'invalid_output',
  'test_passed',
])

export function StudyThreadPage() {
  const { threadId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const messageStreamRef = useRef<HTMLDivElement>(null)
  const shouldFollowRef = useRef(true)
  const [activeRunId, setActiveRunId] = useState(searchParams.get('run') ?? '')
  const thread = useQuery({
    queryKey: ['study-thread', threadId],
    queryFn: () => api<StudyThread>(`/api/v1/study-threads/${threadId}`),
  })
  const providers = useQuery({
    queryKey: ['model-providers'],
    queryFn: () => api<ModelProvider[]>('/api/v1/model-providers'),
  })
  const primary = providers.data?.find(
    (item) => item.role === 'primary' && item.is_enabled,
  )
  const run = useQuery({
    queryKey: ['agent-run', activeRunId],
    queryFn: () => api<AgentRun>(`/api/v1/agent-runs/${activeRunId}`),
    enabled: Boolean(activeRunId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && terminalRunStates.has(status) ? false : 1_500
    },
  })
  const send = useMutation({
    mutationFn: async ({ content, files, explicitConsent }: { content: string; files: File[]; explicitConsent: boolean }) => {
      if (!primary) throw new Error('请先连接一个主模型')
      const message = await addStudyMessage(threadId, content, files)
      const nextRun = await startStudyHelpRun(
        threadId,
        message.message_id,
        primary.provider_id,
        explicitConsent,
      )
      return nextRun
    },
    onSuccess: async (nextRun) => {
      setActiveRunId(nextRun.run_id)
      setSearchParams({ run: nextRun.run_id }, { replace: true })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['study-thread', threadId] }),
        queryClient.invalidateQueries({ queryKey: ['study-threads'] }),
      ])
    },
  })
  const promote = useMutation({
    mutationFn: () => api<{ import_id: string }>(
      `/api/v1/study-threads/${threadId}/promote`,
      { method: 'POST' },
    ),
    onSuccess: (job) => navigate(`/content-studio?import=${job.import_id}`),
  })
  const resolveProposal = useMutation({
    mutationFn: ({ proposalId, decision }: { proposalId: string; decision: 'confirm' | 'dismiss' }) => (
      api<TutorProposal>(`/api/v1/tutor/proposals/${proposalId}/resolve`, {
        method: 'POST',
        body: jsonBody({ decision }),
      })
    ),
    onSuccess: async (proposal) => {
      await thread.refetch()
      const route = proposal.result?.route
      if (proposal.status === 'executed' && typeof route === 'string') navigate(route)
    },
  })

  useEffect(() => {
    if (!run.data || !terminalRunStates.has(run.data.status)) return
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['study-thread', threadId] }),
      queryClient.invalidateQueries({ queryKey: ['study-threads'] }),
    ])
  }, [queryClient, run.data, threadId])

  useEffect(() => {
    const stream = messageStreamRef.current
    if (!stream || !shouldFollowRef.current) return
    const frame = window.requestAnimationFrame(() => {
      stream.scrollTop = stream.scrollHeight
    })
    return () => window.cancelAnimationFrame(frame)
  }, [thread.data?.messages.length, run.data?.status])

  if (thread.isPending) return <LoadingState label="正在打开学习对话" />
  if (thread.isError) return <ErrorState error={thread.error} />

  const activeRun = run.data
  const running = Boolean(
    activeRun && !terminalRunStates.has(activeRun.status),
  )

  return (
    <div className="study-thread-page">
      <header className="study-thread-header">
        <Link className="thread-back" to="/today"><ArrowLeft size={16} />今天</Link>
        <h1>{thread.data.title}</h1>
        <div className="thread-header-actions">
          {thread.data.attachments.length > 0 && (
            <button
              className="thread-promote-action"
              type="button"
              disabled={promote.isPending}
              onClick={() => promote.mutate()}
            >
              <BookOpenCheck size={16} />
              整理成练习
            </button>
          )}
          <ThreadActions
            thread={thread.data}
            onDeleted={() => navigate('/today', { replace: true })}
          />
        </div>
      </header>

      <div className="study-thread-layout">
        <main className="study-dialogue" aria-label="IELTS 学习对话">
          <div
            className="study-message-stream"
            ref={messageStreamRef}
            onScroll={(event) => {
              const element = event.currentTarget
              shouldFollowRef.current = (
                element.scrollHeight - element.scrollTop - element.clientHeight < 120
              )
            }}
          >
            {thread.data.messages.map((message) => (
              <article
                className={`study-message ${message.role}`}
                key={message.message_id}
              >
                {message.role === 'assistant' && (
                  <div className="message-role">IELTS 教师</div>
                )}
                {message.role === 'assistant' && message.context.result
                  ? <StudyHelpAnswer result={message.context.result} />
                  : <p className="message-copy">{message.content}</p>}
                {message.attachments.length > 0 && (
                  <MessageAttachments
                    threadId={threadId}
                    attachments={message.attachments}
                  />
                )}
              </article>
            ))}
            {activeRun && !['persisted', 'test_passed'].includes(activeRun.status) && (
              <ThreadRunState run={activeRun} running={running} />
            )}
            {thread.data.proposals.map((proposal) => (
              <TutorProposalCard
                key={proposal.proposal_id}
                proposal={proposal}
                pending={resolveProposal.isPending}
                onResolve={(decision) => resolveProposal.mutate({
                  proposalId: proposal.proposal_id,
                  decision,
                })}
              />
            ))}
            {(send.error || run.error || promote.error) && (
              <StudyErrorNotice error={send.error ?? run.error ?? promote.error} />
            )}
            <div className="thread-scroll-anchor" aria-hidden="true" />
          </div>

          <div className="thread-composer-wrap">
            <MaterialComposer
              onSend={async (content, files) => {
                if (!primary) return false
                const explicitConsent = requestRemoteProcessingConsent(primary)
                if (explicitConsent === null) return false
                shouldFollowRef.current = true
                await send.mutateAsync({ content, files, explicitConsent })
              }}
              pending={send.isPending || running}
              disabled={!primary}
              placeholder="继续追问，或补充新的截图和文档…"
              compact
            />
          </div>
        </main>
      </div>
    </div>
  )
}

function TutorProposalCard({
  proposal,
  pending,
  onResolve,
}: {
  proposal: TutorProposal
  pending: boolean
  onResolve: (decision: 'confirm' | 'dismiss') => void
}) {
  return (
    <aside className="tutor-proposal-card" aria-label="老师建议的下一步">
      <span className="tutor-proposal-icon"><Sparkles size={16} /></span>
      <span className="tutor-proposal-copy">
        <strong>{proposal.title}</strong>
        <small>{proposal.rationale}</small>
      </span>
      <span className="tutor-proposal-actions">
        <button type="button" disabled={pending} onClick={() => onResolve('dismiss')}>暂不</button>
        <button className="primary" type="button" disabled={pending} onClick={() => onResolve('confirm')}>确认</button>
      </span>
    </aside>
  )
}

function StudyErrorNotice({ error }: { error: unknown }) {
  const technicalMessage = error instanceof Error ? error.message : String(error)
  return (
    <details className="thread-run-failure study-error-notice">
      <summary>
        <span>这次没有收到老师的回答，你的消息和材料仍保存在本机。</span>
        <small>查看技术信息</small>
      </summary>
      <p>{technicalMessage}</p>
    </details>
  )
}

function ThreadRunState({ run, running }: { run: AgentRun; running: boolean }) {
  const failure = run.result?.error?.message
  if (failure) {
    return (
      <details className="thread-run-failure">
        <summary>
          <span>本次回答没有完成</span>
          <small>查看原因</small>
        </summary>
        <p>{failure}</p>
      </details>
    )
  }
  return (
    <div className="thread-run-progress" aria-live="polite">
      {running && <LoaderCircle className="spin" size={16} />}
      <span>{runLabel(run.status)}</span>
      <small>{run.model_display_name ?? run.model_id ?? '当前模型'}</small>
    </div>
  )
}

function StudyHelpAnswer({ result }: { result: StudyHelpResult }) {
  if (result.request_kind === 'teacher_dialogue') {
    return (
      <div className="study-help-answer teacher-dialogue-answer">
        <p className="answer-summary">{result.summary}</p>
        {result.sections.map((section) => (
          <section key={`${section.title}-${section.content.slice(0, 20)}`}>
            <h2>{section.title}</h2>
            <p>{section.content}</p>
          </section>
        ))}
        {result.next_action && <p className="answer-next">{result.next_action}</p>}
      </div>
    )
  }
  return (
    <div className="study-help-answer">
      <div className="answer-meta">
        <StatusBadge tone={
          result.evidence_status === 'sufficient'
            ? 'success'
            : result.evidence_status === 'not_required'
              ? 'neutral'
              : 'warning'
        }>
          {evidenceLabel(result.evidence_status)}
        </StatusBadge>
        <span>{answerLabel(result.answer_status)}</span>
      </div>
      <p className="answer-summary">{result.summary}</p>
      {result.sections.map((section) => (
        <section key={`${section.title}-${section.content.slice(0, 20)}`}>
          <h2>{section.title}</h2>
          <p>{section.content}</p>
        </section>
      ))}
      {result.evidence.length > 0 && (
        <details className="answer-evidence">
          <summary>查看原文依据</summary>
          {result.evidence.map((item, index) => (
            <div key={`${item.source}-${index}`}>
              <strong>{item.claim}</strong>
              {item.quote && <blockquote>{item.quote}</blockquote>}
              <small>{item.source}</small>
            </div>
          ))}
        </details>
      )}
      {result.limitations.length > 0 && (
        <aside className="answer-limit">
          {result.limitations.map((item) => <p key={item}>{item}</p>)}
        </aside>
      )}
      {result.next_action && <p className="answer-next"><strong>下一步：</strong>{result.next_action}</p>}
    </div>
  )
}

function MessageAttachments({ threadId, attachments }: {
  threadId: string
  attachments: StudyThread['attachments']
}) {
  return (
    <details className="message-materials">
      <summary>
        <Paperclip size={15} />
        <span>{attachments.length} 份材料</span>
        <ChevronDown size={14} />
      </summary>
      <div className="message-material-list">
        {attachments.map((attachment) => (
          <AttachmentLink
            key={attachment.attachment_id}
            threadId={threadId}
            attachment={attachment}
          />
        ))}
      </div>
    </details>
  )
}

function AttachmentLink({ threadId, attachment }: {
  threadId: string
  attachment: StudyThread['attachments'][number]
}) {
  const href = `/api/v1/study-threads/${threadId}/attachments/${attachment.attachment_id}/content`
  return (
    <a
      className="study-attachment-link"
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      {attachment.file_kind === 'image'
        ? <img src={href} alt="" />
        : <span className="attachment-file-icon">{attachment.file_kind === 'pdf' ? <FileText size={18} /> : <ImageIcon size={18} />}</span>}
      <span>
        <strong>{attachment.original_name}</strong>
        <small>{extractionLabel(attachment.extraction_status)}</small>
      </span>
    </a>
  )
}

function runLabel(status: string) {
  return ({
    queued: '已排队',
    running: '正在阅读材料',
    validating: '正在核对讲解结构',
    persisting: '正在保存对话',
    persisted: '讲解已保存',
    failed: '调用失败',
    invalid_output: '讲解格式无效',
    cancelled: '已取消',
  } as Record<string, string>)[status] ?? status
}

function evidenceLabel(status: StudyHelpResult['evidence_status']) {
  return status === 'not_required'
    ? '自然对话'
    : status === 'sufficient'
      ? '证据充分'
      : status === 'partial'
        ? '部分证据'
        : '证据不足'
}

function answerLabel(status: StudyHelpResult['answer_status']) {
  return ({
    withheld: '答案暂不揭示',
    unverified: '答案未经权威核验',
    verified: '答案已有依据',
    not_applicable: '不涉及答案',
  } as Record<string, string>)[status]
}

function extractionLabel(status: string) {
  return ({
    visual_only: '由视觉模型读取',
    text_available: '文字已提取',
    ocr_required: '需要 OCR',
    password_required: '需要 PDF 密码',
    extraction_failed: '文字提取失败',
  } as Record<string, string>)[status] ?? '本地材料'
}
