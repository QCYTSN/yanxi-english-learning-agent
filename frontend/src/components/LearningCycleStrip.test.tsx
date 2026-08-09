import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TeachingCycle } from '../api/client'
import { LearningCycleStrip } from './LearningCycleStrip'

const cycle: TeachingCycle = {
  cycle_id: 'cycle-1',
  track_id: 'ielts-academic',
  dimension_id: 'reading',
  skill_id: 'reading.inference',
  objective_id: null,
  activity_id: null,
  thread_id: 'thread-1',
  session_id: null,
  title: '区分 False 与 Not Given',
  phase: 'guided_practice',
  status: 'active',
  revision: 2,
  context: {},
  source_type: 'runtime',
  source_id: null,
  started_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
  completed_at: null,
  recommendation: {
    action: 'transition',
    target_phase: 'independent_practice',
    reason_code: 'guided_practice_complete',
    deterministic: true,
    applied: false,
    mastery: null,
  },
}

describe('LearningCycleStrip', () => {
  it('shows a human teaching path without runtime vocabulary', () => {
    render(<LearningCycleStrip cycle={cycle} />)
    expect(screen.getByRole('region', { name: '当前教学进度' })).toHaveTextContent('一起练习')
    expect(screen.getByText('下一步：独立完成')).toBeInTheDocument()
    expect(screen.queryByText('guided_practice')).not.toBeInTheDocument()
  })
})
