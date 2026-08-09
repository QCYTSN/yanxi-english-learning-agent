import { describe, expect, it } from 'vitest'
import type { LearningSkill, TeachingCycleRecommendation } from './api/client'
import {
  masteryPresentation,
  memoryTypeLabel,
  phaseMeta,
  recommendationCopy,
  skillPresentation,
} from './learningPresentation'

describe('learning presentation', () => {
  it('turns runtime phases into learner-facing language', () => {
    expect(phaseMeta('guided_practice').label).toBe('一起练习')
    expect(recommendationCopy({
      action: 'transition',
      target_phase: 'independent_practice',
      reason_code: 'ready',
      deterministic: true,
      applied: false,
      mastery: null,
    } satisfies TeachingCycleRecommendation)).toBe('下一步：独立完成')
  })

  it('does not present missing evidence as a low score', () => {
    const skill = {
      skill_id: 'reading.inference',
      dimension_id: 'reading',
      title: '推断与逻辑判断',
      mastery: null,
    } as LearningSkill
    expect(masteryPresentation(skill)).toMatchObject({
      label: '尚无证据',
      percent: 0,
      detail: '完成相关练习后再判断',
    })
  })

  it('labels learner memory without exposing storage vocabulary', () => {
    expect(memoryTypeLabel({ memory_type: 'preference', scope: 'teaching_style' })).toBe('学习偏好')
  })

  it('keeps stable skill ids while localising learner-facing copy', () => {
    expect(skillPresentation({
      skill_id: 'reading.inference',
      title: 'Inference and logical status',
      description: 'Technical source description',
    })).toEqual({
      title: '推断与逻辑判断',
      description: '区分原文明示、明确反驳和没有提供信息。',
    })
  })
})
