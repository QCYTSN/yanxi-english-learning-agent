import { describe, expect, it } from 'vitest'
import { normalisePerformance } from './settingsPerformance'

describe('SettingsPage performance compatibility', () => {
  it('accepts the partial response returned by an older local service', () => {
    expect(normalisePerformance({ database: { size_bytes: 4096 } })).toEqual({
      sampleCount: 0,
      p50Ms: 0,
      p95Ms: 0,
      slowestRoutes: [],
      databaseSizeBytes: 4096,
      journalMode: 'UNKNOWN',
      busyTimeoutMs: 0,
      rowCounts: {},
      nativeAccelerationEnabled: false,
      nativeAccelerationReason: '当前后端未提供原生加速诊断。',
    })
  })
})
