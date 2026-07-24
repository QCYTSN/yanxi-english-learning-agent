export type PerformanceResponse = {
  requests?: {
    sample_count?: number
    average_ms?: number | null
    p50_ms?: number | null
    p95_ms?: number | null
    slowest_routes?: Array<{ route: string; requests: number; average_ms: number; p95_ms: number }>
  }
  database?: {
    size_bytes?: number
    reclaimable_bytes?: number
    pragmas?: { journal_mode?: string; busy_timeout_ms?: number; cache_size?: number }
    row_counts?: Record<string, number>
    native_acceleration?: { enabled?: boolean; decision?: string; reason?: string }
  }
}

export function normalisePerformance(value?: PerformanceResponse) {
  return {
    sampleCount: value?.requests?.sample_count ?? 0,
    p50Ms: value?.requests?.p50_ms ?? 0,
    p95Ms: value?.requests?.p95_ms ?? 0,
    slowestRoutes: Array.isArray(value?.requests?.slowest_routes) ? value.requests.slowest_routes : [],
    databaseSizeBytes: value?.database?.size_bytes ?? 0,
    journalMode: String(value?.database?.pragmas?.journal_mode ?? 'unknown').toUpperCase(),
    busyTimeoutMs: value?.database?.pragmas?.busy_timeout_ms ?? 0,
    rowCounts: value?.database?.row_counts ?? {},
    nativeAccelerationEnabled: Boolean(value?.database?.native_acceleration?.enabled),
    nativeAccelerationReason: value?.database?.native_acceleration?.reason ?? '当前后端未提供原生加速诊断。',
  }
}
