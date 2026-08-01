export type ApiErrorPayload = {
  error?: {
    code?: string
    message?: string
    recoverable?: boolean
    details?: Record<string, unknown>
  }
  detail?: string
}

export class ApiError extends Error {
  code: string
  status: number
  details: Record<string, unknown>

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.error?.message ?? payload.detail ?? `Request failed (${status})`)
    this.name = 'ApiError'
    this.code = payload.error?.code ?? 'REQUEST_FAILED'
    this.status = status
    this.details = payload.error?.details ?? {}
  }
}

export type SessionSummary = {
  session_id: string
  module: 'listening' | 'reading' | 'writing' | 'speaking'
  status: string
  revision?: number
  band?: number | null
  occurred_at?: string
  question_id?: string | null
  passage_id?: string | null
  mode?: string | null
  [key: string]: unknown
}

export type Bootstrap = {
  api_version: number
  core_version: string
  setup_required: boolean
  onboarding: { status: string; baseline_status: string } | null
  profile: {
    exam_type: string
    test_date?: string | null
    target: Record<string, number>
    minimum_required: Record<string, number>
    current: Record<string, number | null>
    preferences: Record<string, unknown>
    privacy: Record<string, boolean>
  } | null
  active_session: SessionSummary | null
  health: Record<string, boolean>
  agents: AgentDescriptor[]
  capabilities: CapabilityDescriptor[]
  execution_profiles: ExecutionProfile[]
  model_providers: ModelProvider[]
  external_agents: ExternalAgentProfile[]
  ai_setup_required: boolean
  storage: {
    data_home: string
    database_path: string
    backups_path: string
  }
}

export type AgentDescriptor = {
  id: string
  label: string
  available: boolean
  capabilities: Record<string, boolean>
  identity: {
    agent_provider: string | null
    agent_version: string | null
    model_id: string | null
    model_display_name: string | null
    launcher_kind: string
    calibration_status: string
  }
}

export type CapabilityDescriptor = {
  capability_id: string
  title: string
  module: string
  output_contract: string
  skill: string
  privacy_scope: 'learning_record' | 'private_material'
  media_types: Array<'image' | 'audio'>
  default_timeout_seconds: number
}

export type ExecutionProfile = {
  profile_id: string
  display_name: string
  backend_kind: 'managed_runtime' | 'api_model' | 'local_http_model' | 'model_provider' | 'external_agent' | 'manual' | 'mock'
  backend_id: string
  transport: string
  auth_mode: string
  model_id: string | null
  reasoning_effort: string | null
  is_enabled: boolean
  is_default: boolean
  config: { executable_path?: string; [key: string]: unknown }
  available?: boolean
  capabilities?: Record<string, boolean>
  identity?: AgentDescriptor['identity']
  diagnostics?: {
    executable_path?: string | null
    version?: string | null
      error?: string | null
      boundary?: string
      source?: 'configured' | 'environment' | 'managed' | 'path' | null
      isolated_codex_home?: string | null
      shares_global_codex_auth?: boolean
      managed_runtime?: {
        installed: boolean
        available: boolean
        pinned_version: string
        executable_path?: string | null
      }
    }
  }

export type ModelProvider = {
  provider_id: string
  display_name: string
  provider_kind: 'codex_oauth_bridge' | 'openai_compatible' | 'local_http'
  transport: 'codex_app_server' | 'http'
  auth_mode: 'oauth' | 'api_key' | 'none'
  base_url: string | null
  model_id: string | null
  reasoning_effort: string | null
  role: 'primary' | 'fallback' | 'disabled'
  fallback_order: number | null
  is_enabled: boolean
  credential_configured: boolean
  credential_protection: 'windows_dpapi' | 'owner_only_file'
  config: {
    executable_path?: string
    image_input?: boolean
    temperature?: number
    timeout_seconds?: number
    [key: string]: unknown
  }
  available?: boolean
  diagnostics?: Record<string, unknown>
}

export type ExternalAgentProfile = {
  agent_profile_id: string
  display_name: string
  adapter_id: string
  purpose: string
  is_enabled: boolean
  available: boolean
  teaching_model_eligible: false
  boundary: string
  capabilities: Record<string, boolean>
  identity: AgentDescriptor['identity']
  diagnostics?: Record<string, unknown>
}

export type LearningIntentResult = {
  intent_version: number
  intent_kind: 'resume' | 'open_module' | 'review' | 'choose_practice'
  module: 'listening' | 'reading' | 'writing' | 'speaking' | null
  route: string
  title: string
  message: string
  resolved_by: 'teaching_runtime'
  model_called: false
}

export type AgentRun = {
  run_id: string
  study_session_id: string | null
  adapter_id: string
  capability_id: string | null
  execution_profile_id: string | null
  model_provider_id: string | null
  backend_kind: ExecutionProfile['backend_kind']
  transport: string | null
  auth_mode: string | null
  agent_provider: string | null
  agent_version: string | null
  model_id: string | null
  model_display_name: string | null
  agent_session_id: string | null
  launcher_kind: string
  capabilities: Record<string, boolean>
  calibration_status: string
  status: string
  usage: Record<string, unknown>
  created_at: string
  started_at: string | null
  completed_at: string | null
  timeout_seconds: number
  attempt_count: number
  cancel_requested: boolean
  heartbeat_at: string | null
  recovery_action: string | null
  execution_ref: string | null
  skill_hash?: string | null
  inference_route?: string[]
  error_code?: string | null
  result?: {
    request?: Record<string, unknown>
    package_path?: string
    attachments?: Array<{ media_id: string; file: string; mime_type: string }>
    error?: { code: string; message: string }
  } | null
}

export type StudyAttachment = {
  attachment_id: string
  thread_id: string
  message_id: string | null
  original_name: string
  mime_type: string | null
  file_kind: 'image' | 'pdf' | 'text' | 'document'
  size_bytes: number
  sha256: string
  media_id: string | null
  extracted_text: string
  extraction_status: string
  created_at: string
}

export type StudyHelpResult = {
  contract_version: 1
  module: 'reading' | 'writing' | 'mixed'
  request_kind: string
  evidence_status: 'sufficient' | 'partial' | 'insufficient' | 'not_required'
  answer_status: 'withheld' | 'unverified' | 'verified' | 'not_applicable'
  summary: string
  sections: Array<{ title: string; content: string }>
  evidence: Array<{ claim: string; source: string; quote?: string | null }>
  limitations: string[]
  next_action: string | null
}

export type StudyMessage = {
  message_id: string
  thread_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  status: string
  context: { result?: StudyHelpResult; [key: string]: unknown }
  agent_run_id: string | null
  created_at: string
  attachments: StudyAttachment[]
}

export type StudyThread = {
  thread_id: string
  title: string
  module: 'reading' | 'writing' | 'mixed'
  status: string
  model_provider_id: string | null
  source_context: Record<string, unknown>
  created_at: string
  updated_at: string
  messages: StudyMessage[]
  attachments: StudyAttachment[]
  message_count: number
  attachment_count: number
  last_message_preview: string
}

export type TodayPlanTask = {
  module: 'listening' | 'reading' | 'writing' | 'speaking'
  share: number
  title: string
  reason: string
  estimated_minutes: number
  target_band: number | null
  recent_band: number | null
  target_gap: number | null
  content_available: boolean
  practice_mode: string
  fallback: boolean
  route: string
}

export type PracticeUnit = {
  unit_id: string
  unit_kind: 'diagnostic' | 'practice' | 'review'
  module: 'listening' | 'reading' | 'writing' | 'speaking' | null
  title: string
  status: 'planned' | 'in_progress' | 'completed' | 'cancelled'
  scheduled_for: string
  route: string
  launch_url: string
  estimated_minutes: number | null
  diagnostic_id: string | null
  session_id: string | null
  assessment_run_id: string | null
  payload: Record<string, unknown>
}

export type ReviewTask = {
  review_task_id: string
  module: 'listening' | 'reading' | 'writing' | 'speaking'
  review_kind: 'error_review' | 'listening_expression' | 'writing_revision' | 'reading_wrong_answer'
  status: 'pending' | 'in_progress' | 'completed' | 'dismissed'
  priority: number
  due_at: string
  session_id: string | null
  title: string
  action: string
  route: string
  payload: Record<string, unknown>
  practice_unit_id: string | null
}

export type StudyContext = {
  context_version: number
  next_action: string
  allocation: Record<string, number>
  allocation_reasons: string[]
  today_plan: {
    strategy: '70_30'
    primary: TodayPlanTask
    consolidation: TodayPlanTask
    verified_full_mock_count: number
  }
  review_queue?: {
    counts: Record<string, number>
    items: ReviewTask[]
  }
  practice_units?: PracticeUnit[]
}

export type ProgressDashboard = {
  dashboard_version: number
  window_days: number
  generated_at: string
  modules: Record<string, {
    completed_sessions: number
    eligible_samples: number
    observation_samples: number
    average_band: number | null
    target: number | null
    gap: number | null
    trend: ProgressTrendSample[]
    trend_buckets: Array<{
      period: string
      period_start: string
      average_band: number | null
      eligible_samples: number
      observation_samples: number
    }>
    trend_summary: {
      direction: 'improving' | 'declining' | 'stable' | 'insufficient'
      delta: number | null
      early_average: number | null
      recent_average: number | null
      sample_count: number
    }
  }>
  criteria: Record<string, Array<{ criterion: string; average: number; samples: number; first: number; latest: number; eligible_samples: number; evidence_class: string }>>
  reading_question_types: Array<{ question_type: string; attempts: number; correct: number; accuracy: number; average_seconds: number | null }>
  listening: {
    scenes: Array<{ scene: string; attempts: number }>
    error_types: Array<{ type: string; count: number }>
  }
  errors: {
    counts: Record<string, number>
    items: Array<{ module: string; tag: string; status: string; count: number; sessions: number; last_seen: string }>
  }
  weekly: { allocation: Record<string, number>; reasons: string[] }
  next_actions: ProgressAction[]
}

export type ProgressTrendSample = {
  session_id: string
  occurred_at: string
  band: number
  eligible: boolean
  score_kind: string
  confidence: string
}

export type ProgressAction = {
  action_id: string
  action_kind: 'review' | 'diagnostic' | 'practice'
  module: string | null
  title: string
  reason: string
  priority: number
  estimated_minutes: number
  route: string
  review_task_id?: string
  practice_mode?: string
}

export type WeeklyReport = {
  report_version: number
  report_id: string
  period_key: string
  period_start: string
  period_end: string
  generated_at: string
  source_counts: {
    completed_sessions: number
    completed_practice_units: number
    estimated_minutes: number
    completed_reviews: number
    review_backlog: number
  }
  modules: Record<string, {
    completed_sessions: number
    eligible_samples: number
    observation_samples: number
    average_band: number | null
    previous_average_band: number | null
    change: number | null
    target: number | null
    gap: number | null
  }>
  wins: string[]
  risks: string[]
  allocation: { allocation: Record<string, number>; reasons: string[] }
  next_actions: ProgressAction[]
  markdown: string
  source_hash: string
}

export type Draft = {
  session_id: string
  draft_kind: string
  revision: number
  payload: Record<string, unknown>
  updated_at: string | null
}

export type Question = {
  question_id: string
  module: string
  task?: string | null
  part?: string | number | null
  question_type?: string | null
  question_number?: string | number | null
  title?: string | null
  content: string
  passage_id?: string | null
  passage_title?: string | null
  topics_text?: string | null
  task_data?: Record<string, unknown>
  media_id?: string | null
  media_ids?: string[]
  source_group_text?: string
  question_group_id?: string
  question_group_start?: number
  question_group_end?: number
  options?: Record<string, string> | Array<{ key: string; text: string }>
  answer_constraints?: { word_limit?: number; words_from_passage?: boolean; [key: string]: unknown }
  minimum_words?: number
  practice_mode?: 'full_mock' | 'section_practice' | 'question_type_drill' | 'skill_drill'
  standard_profile?: string
  conformance_status?: 'verified' | 'provisional' | 'skill_only' | 'rejected'
  local_review_status?: 'approved' | 'stale' | 'changes_requested' | 'rejected' | 'unreviewed'
  conformance_report?: { errors?: string[]; warnings?: string[]; [key: string]: unknown }
  source_type?: string
  topics?: string[]
  [key: string]: unknown
}

export type AssessmentPack = {
  pack_id: string
  title: string
  module: 'listening' | 'reading' | 'writing' | 'speaking'
  practice_mode: string
  conformance_status: string
  local_review_status?: string
  structure?: Record<string, unknown>
}

export type AssessmentResponse = {
  question_id: string
  section_key: string
  revision: number
  response: { answer?: string | string[]; text?: string }
  flagged: boolean
}

export type AssessmentRun = {
  run_id: string
  pack_id: string
  session_id: string
  module: 'listening' | 'reading' | 'writing' | 'speaking'
  practice_mode: string
  status: string
  revision: number
  pack_hash: string
  pack_snapshot: AssessmentPack & {
    questions: Question[]
    passages?: Record<string, { passage_id: string; title?: string; body: string }>
    structure: Record<string, unknown>
  }
  timer: {
    authoritative_at: string
    time_limit_seconds: number | null
    elapsed_active_seconds: number
    remaining_seconds: number | null
    running: boolean
    pause_allowed: boolean
    expired: boolean
  }
  navigation: Record<string, unknown>
  media_state: Record<string, { play_count?: number; position_seconds?: number; completed?: boolean }>
  submission: Record<string, unknown>
  score_result: Record<string, unknown>
  sections: Array<{ section_key: string; status: string; payload: Record<string, unknown> }>
  responses: AssessmentResponse[]
  playback_lease?: {
    token: string
    expires_at: string
    run_id: string
    media_id: string
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const method = (init.method ?? 'GET').toUpperCase()
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !headers.has('X-IELTS-CSRF')) {
    const csrfToken = readCookie('ielts_ui_csrf')
    if (csrfToken) headers.set('X-IELTS-CSRF', csrfToken)
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    if (response.status === 204) return undefined as T
    if (!response.ok) throw new ApiError(response.status, {})
    throw new ApiError(502, {
      error: {
        code: 'INVALID_API_RESPONSE',
        message: '本地服务版本与当前页面不一致。请关闭旧窗口并重新启动 IELTS Study Desk。',
        recoverable: true,
        details: { path, content_type: contentType || 'missing' },
      },
    })
  }
  const payload = (await response.json()) as T & ApiErrorPayload
  if (!response.ok) throw new ApiError(response.status, payload)
  return payload
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${encodeURIComponent(name)}=`
  const item = document.cookie.split(';').map((value) => value.trim()).find((value) => value.startsWith(prefix))
  return item ? decodeURIComponent(item.slice(prefix.length)) : null
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value)
}

export function idempotencyKey(): string {
  return crypto.randomUUID()
}

export async function establishUiSession(): Promise<void> {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const launchToken = params.get('launch_token')
  if (!launchToken) return
  const requestedPath = window.location.pathname === '/'
    ? '/today'
    : `${window.location.pathname}${window.location.search}`
  await api('/api/auth/exchange', {
    method: 'POST',
    body: jsonBody({ token: launchToken }),
  })
  window.history.replaceState(null, '', requestedPath)
}
