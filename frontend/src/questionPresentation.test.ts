import { describe, expect, it } from 'vitest'
import type { Question } from './api/client'
import {
  questionDisplayTitle,
  questionMatchesFilter,
  questionTypeLabel,
} from './questionPresentation'

const question = (updates: Partial<Question>): Question => ({
  question_id: 'q-1',
  module: 'reading',
  content: 'Question text',
  ...updates,
})

describe('question presentation', () => {
  it('uses the passage title instead of an internal reading identifier', () => {
    expect(questionDisplayTitle(question({
      passage_id: 'cambridge-21:test-1:passage-1',
      passage_title: 'The Egyptian Pyramids',
    }))).toBe('The Egyptian Pyramids')
  })

  it('turns a Task 1 prompt into a concise topic title', () => {
    expect(questionDisplayTitle(question({
      module: 'writing',
      task: 'task1',
      content: 'WRITING TASK 1 You should spend about 20 minutes on this task. The chart below shows coffee and tea buying and drinking habits in five Australian cities.',
    }))).toBe('Coffee and tea buying and drinking habits in five Australian cities.')
  })

  it('groups IELTS Reading question types into learner-facing categories', () => {
    const judgement = question({ question_type: 'true_false_not_given' })
    const completion = question({ question_type: 'summary_completion' })
    expect(questionMatchesFilter(judgement, 'judgement')).toBe(true)
    expect(questionMatchesFilter(judgement, 'completion')).toBe(false)
    expect(questionMatchesFilter(completion, 'completion')).toBe(true)
    expect(questionTypeLabel('matching_headings')).toBe('段落标题匹配')
  })

  it('localises common Speaking topics into useful titles', () => {
    expect(questionDisplayTitle(question({
      module: 'speaking',
      part: 3,
      topics_text: 'education technology',
    }))).toBe('教育与学习 · 科技与生活')
  })
})
