import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  BookOpenCheck,
  ChevronDown,
  FileText,
  Image as ImageIcon,
  LoaderCircle,
  MessageCircle,
  Paperclip,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  jsonBody,
  type AgentRun,
  type AgentRunEvent,
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
  const [runEvent, setRunEvent] = useState<AgentRunEvent | null>(null)
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
      return status && terminalRunStates.has(status) ? false : 5_000
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
    setRunEvent(null)
    if (!activeRunId) return
    const source = new EventSource(`/api/v1/agent-runs/${activeRunId}/events`)
    const eventNames = [
      'job_queued', 'context_preparing', 'context_ready', 'skill_compiled',
      'provider_started', 'provider_stream_delta', 'provider_progress',
      'provider_completed', 'provider_failed', 'fallback_started',
      'schema_validation_started', 'schema_validation_failed',
      'domain_validation_started', 'domain_validation_failed',
      'persistence_started', 'persisted', 'pipeline_test_passed',
      'job_failed', 'job_cancelled', 'tutor_planning', 'tool_started',
      'tool_completed', 'tutor_answering',
    ]
    const terminalEvents = new Set([
      'persisted', 'pipeline_test_passed', 'job_failed', 'job_cancelled',
    ])
    const receive = (event: MessageEvent<string>) => {
      try {
        const next = JSON.parse(event.data) as AgentRunEvent
        setRunEvent(next)
        if (terminalEvents.has(next.type)) {
          source.close()
          void queryClient.invalidateQueries({ queryKey: ['agent-run', activeRunId] })
        }
      } catch {
        // A malformed progress frame should not interrupt the learning turn.
      }
    }
    eventNames.forEach((name) => source.addEventListener(name, receive as EventListener))
    source.onerror = () => {
      void queryClient.invalidateQueries({ queryKey: ['agent-run', activeRunId] })
    }
    return () => source.close()
  }, [activeRunId, queryClient])

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
              <ThreadRunState run={activeRun} event={runEvent} running={running} />
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

function ThreadRunState({ run, event, running }: {
  run: AgentRun
  event: AgentRunEvent | null
  running: boolean
}) {
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
  const state = runProgressState(run, event)
  return (
    <div className="thread-run-progress" aria-live="polite">
      <span className="thread-run-icon" aria-hidden="true">
        <RunProgressIcon kind={state.icon} running={running} />
      </span>
      <span className="thread-run-copy">
        <strong>{state.title}</strong>
        <small>{state.detail}</small>
      </span>
      <small className="thread-run-model">{run.model_display_name ?? run.model_id ?? '当前模型'}</small>
    </div>
  )
}

function RunProgressIcon({ kind, running }: { kind: RunProgressState['icon']; running: boolean }) {
  const props = { size: 17, strokeWidth: 1.8 }
  if (kind === 'search') return <Search {...props} />
  if (kind === 'verify') return <ShieldCheck {...props} />
  if (kind === 'save') return <Save {...props} />
  if (kind === 'answer') return <MessageCircle {...props} />
  return <LoaderCircle {...props} className={running ? 'spin' : undefined} />
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

type RunProgressState = {
  title: string
  detail: string
  icon: 'wait' | 'search' | 'answer' | 'verify' | 'save'
}

const toolProgress: Record<string, RunProgressState> = {
  inspect_thread_material: { title: '正在查看材料', detail: '读取你在本次对话中提供的内容', icon: 'search' },
  locate_passage_evidence: { title: '正在定位原文依据', detail: '在材料中寻找与问题最相关的段落', icon: 'search' },
  get_question_context: { title: '正在核对题目要求', detail: '保持题目与答案揭示规则完整', icon: 'verify' },
  get_learner_snapshot: { title: '正在了解你的学习情况', detail: '只读取本机已有的学习证据', icon: 'search' },
  get_due_reviews: { title: '正在查看待复习内容', detail: '寻找当前最值得巩固的项目', icon: 'search' },
  find_approved_materials: { title: '正在寻找合适练习', detail: '只选择已经审核通过的内容', icon: 'search' },
  get_session_status: { title: '正在恢复练习进度', detail: '核对正式练习的当前状态', icon: 'search' },
  search_learning_history: { title: '正在回顾相关记录', detail: '查找与当前问题有关的学习证据', icon: 'search' },
  get_learner_memories: { title: '正在读取教学偏好', detail: '沿用你确认过的学习方式', icon: 'search' },
  get_teaching_policy: { title: '正在核对教学规则', detail: '确保讲解符合 IELTS 学习边界', icon: 'verify' },
  compare_writing_versions: { title: '正在比较作文版本', detail: '定位你两次修改之间的具体变化', icon: 'search' },
  propose_practice_session: { title: '正在准备练习建议', detail: '完成后由你决定是否开始', icon: 'answer' },
  propose_review_item: { title: '正在准备复习建议', detail: '完成后由你决定是否加入队列', icon: 'answer' },
  propose_learner_memory: { title: '正在准备学习偏好', detail: '只有你确认后才会记住', icon: 'answer' },
  propose_material_promotion: { title: '正在准备材料整理建议', detail: '原始材料不会自动进入正式题库', icon: 'answer' },
}

function runProgressState(run: AgentRun, event: AgentRunEvent | null): RunProgressState {
  const eventType = event?.type
  const eventStage = String(event?.payload.stage ?? event?.stage ?? '')
  const tool = String(event?.payload.tool ?? '')
  if (eventType === 'tool_started' && toolProgress[tool]) return toolProgress[tool]
  if (eventType === 'tutor_planning') return { title: '正在规划讲解', detail: '判断这一步需要哪些学习证据', icon: 'search' }
  if (eventType === 'tutor_answering') return { title: '正在组织回答', detail: '把依据整理成清楚、可执行的讲解', icon: 'answer' }
  if (eventType === 'fallback_started') return { title: '正在切换备用模型', detail: '当前连接没有完成，系统正在自动恢复', icon: 'wait' }
  if (eventType === 'schema_validation_started' || eventStage === 'schema_validation') {
    return { title: '正在检查回答', detail: '确认内容完整且可以安全展示', icon: 'verify' }
  }
  if (eventType === 'domain_validation_started' || eventStage === 'domain_validation') {
    return { title: '正在核对教学边界', detail: '检查答案、评分与证据规则', icon: 'verify' }
  }
  if (eventType === 'persistence_started' || run.status === 'persisting') {
    return { title: '正在保存对话', detail: '学习记录只写入你的本机', icon: 'save' }
  }
  if (eventType === 'provider_started' || eventType === 'provider_progress' || eventType === 'provider_stream_delta') {
    return { title: '正在回应你', detail: '当前模型已开始生成回答', icon: 'answer' }
  }
  if (eventType === 'context_preparing') return { title: '正在整理上下文', detail: '只准备本次回答需要的内容', icon: 'search' }
  if (eventType === 'context_ready' || eventType === 'skill_compiled') {
    return { title: 'IELTS 教师已准备好', detail: '正在连接当前模型', icon: 'wait' }
  }
  if (run.status === 'validating') return { title: '正在检查回答', detail: '确认内容完整且符合教学规则', icon: 'verify' }
  return { title: '正在准备回答', detail: '消息已保存，马上开始处理', icon: 'wait' }
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
