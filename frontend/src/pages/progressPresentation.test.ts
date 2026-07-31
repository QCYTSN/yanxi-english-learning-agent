import { describe, expect, it } from 'vitest'
import type { ProgressTrendSample } from '../api/client'
import { buildTrendGeometry } from './progressPresentation'

const sample = (
  sessionId: string,
  band: number,
  eligible: boolean,
): ProgressTrendSample => ({
  session_id: sessionId,
  occurred_at: '2026-07-24T00:00:00+00:00',
  band,
  eligible,
  score_kind: eligible ? 'official_result' : 'unspecified',
  confidence: eligible ? 'high' : 'low',
})

describe('progress trend presentation', () => {
  it('keeps observations visible without adding them to the trusted line', () => {
    const geometry = buildTrendGeometry([
      sample('eligible-1', 6, true),
      sample('observation', 9, false),
      sample('eligible-2', 7, true),
    ], 7.5)

    expect(geometry.points).toHaveLength(3)
    expect(geometry.path.match(/[ML]/g)).toHaveLength(2)
    expect(geometry.targetY).not.toBeNull()
  })
})
