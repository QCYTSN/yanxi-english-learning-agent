import {
  api,
  idempotencyKey,
  jsonBody,
  type AgentRun,
  type ModelProvider,
  type StudyMessage,
  type StudyThread,
} from './api/client'

export async function createStudyThreadWithMessage({
  content,
  files,
  modelProviderId,
  module = 'mixed',
  context = {},
  explicitConsent = false,
}: {
  content: string
  files: File[]
  modelProviderId: string
  module?: 'reading' | 'writing' | 'mixed'
  context?: Record<string, unknown>
  explicitConsent?: boolean
}) {
  const thread = await api<StudyThread>('/api/v1/study-threads', {
    method: 'POST',
    body: jsonBody({
      title: titleFrom(content),
      module,
      model_provider_id: modelProviderId,
      source_context: context,
    }),
  })
  const message = await addStudyMessage(thread.thread_id, content, files, context)
  const run = await startStudyHelpRun(
    thread.thread_id,
    message.message_id,
    modelProviderId,
    explicitConsent,
  )
  return { thread, message, run }
}

export async function addStudyMessage(
  threadId: string,
  content: string,
  files: File[],
  context: Record<string, unknown> = {},
) {
  const body = new FormData()
  body.append('content', content)
  body.append('context_json', JSON.stringify(context))
  files.forEach((file) => body.append('files', file))
  return api<StudyMessage>(`/api/v1/study-threads/${threadId}/messages`, {
    method: 'POST',
    body,
  })
}

export async function startStudyHelpRun(
  threadId: string,
  messageId: string,
  modelProviderId: string,
  explicitConsent = false,
) {
  return api<AgentRun>('/api/v1/agent-runs', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey() },
    body: jsonBody({
      study_thread_id: threadId,
      user_message_id: messageId,
      model_provider_id: modelProviderId,
      action: 'teacher_dialogue',
      output_contract: 'study-help@1',
      explicit_consent: explicitConsent,
      source_type: 'personal',
      timeout_seconds: 600,
    }),
  })
}

export function requestRemoteProcessingConsent(
  provider: Pick<ModelProvider, 'provider_id' | 'provider_kind' | 'display_name'>,
): boolean | null {
  if (provider.provider_kind === 'local_http') return false
  const storageKey = `ielts-study-desk:remote-consent:${provider.provider_id}`
  if (window.sessionStorage.getItem(storageKey) === 'granted') return true
  const granted = window.confirm(
    `本次学习对话及所附材料将发送给“${provider.display_name}”处理。`
    + '请仅发送你有权使用的内容。是否允许当前浏览器会话使用该模型？',
  )
  if (!granted) return null
  window.sessionStorage.setItem(storageKey, 'granted')
  return true
}

function titleFrom(content: string) {
  const clean = content.replace(/\s+/g, ' ').trim()
  return clean.length > 38 ? `${clean.slice(0, 38)}…` : clean
}
