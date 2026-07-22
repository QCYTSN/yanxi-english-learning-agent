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
    target: Record<string, number>
    minimum_required: Record<string, number>
    current: Record<string, number | null>
  } | null
  active_session: SessionSummary | null
  health: Record<string, boolean>
  agents: AgentDescriptor[]
}

export type AgentDescriptor = {
  id: string
  label: string
  available: boolean
  capabilities: Record<string, boolean>
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
  source_type?: string
  topics?: string[]
  [key: string]: unknown
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
