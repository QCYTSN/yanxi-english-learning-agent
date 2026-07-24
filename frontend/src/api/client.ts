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

export type AgentRun = {
  run_id: string
  study_session_id: string
  adapter_id: string
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
  error_code?: string | null
  result?: {
    request?: Record<string, unknown>
    package_path?: string
    attachments?: Array<{ media_id: string; file: string; mime_type: string }>
    error?: { code: string; message: string }
  } | null
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
}

export type ProgressDashboard = {
  dashboard_version: number
  window_days: number
  modules: Record<string, {
    completed_sessions: number
    eligible_samples: number
    observation_samples: number
    average_band: number | null
    target: number | null
    gap: number | null
    trend: Array<{ session_id: string; occurred_at: string; band: number; eligible: boolean }>
  }>
  criteria: Record<string, Array<{ criterion: string; average: number; samples: number; first: number; latest: number; eligible_samples: number; evidence_class: string }>>
  reading_question_types: Array<{ question_type: string; attempts: number; correct: number; accuracy: number; average_seconds: number | null }>
  listening: {
    scenes: Array<{ scene: string; attempts: number }>
    error_types: Array<{ type: string; count: number }>
  }
  errors: {
    counts: Record<string, number>
    items: Array<{ tag: string; status: string; count: number; sessions: number; last_seen: string }>
  }
  weekly: { allocation: Record<string, number>; reasons: string[] }
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
  question_type?: string | null
  question_number?: string | number | null
  content: string
  passage_id?: string | null
  task_data?: Record<string, unknown>
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
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const contentType = response.headers.get('content-type') ?? ''
  const payload = contentType.includes('application/json')
    ? ((await response.json()) as T & ApiErrorPayload)
    : ({} as T & ApiErrorPayload)
  if (!response.ok) throw new ApiError(response.status, payload)
  return payload
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
  await api('/api/auth/exchange', {
    method: 'POST',
    body: jsonBody({ token: launchToken }),
  })
  window.history.replaceState(null, '', '/today')
}
