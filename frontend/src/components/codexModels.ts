export type CodexModel = {
  id?: string
  model?: string
  displayName?: string
  supportedReasoningEfforts?: Array<string | { reasoningEffort?: string }>
  defaultReasoningEffort?: string
  isDefault?: boolean
}

export type CodexModels = {
  data?: CodexModel[]
  models?: CodexModel[]
}

export type NormalisedCodexModel = Omit<CodexModel, 'supportedReasoningEfforts'> & {
  supportedReasoningEfforts: string[]
}

export function normaliseCodexModels(payload: CodexModels | undefined): NormalisedCodexModel[] {
  const source = Array.isArray(payload?.data)
    ? payload.data
    : Array.isArray(payload?.models)
      ? payload.models
      : []
  return source.map((item) => ({
    ...item,
    supportedReasoningEfforts: (item.supportedReasoningEfforts ?? [])
      .map((effort) => typeof effort === 'string' ? effort : effort.reasoningEffort)
      .filter((effort): effort is string => Boolean(effort)),
  }))
}
