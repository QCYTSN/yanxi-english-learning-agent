import type { Question } from './api/client'

const TOPIC_LABELS: Record<string, string> = {
  accommodation: '住宿与居住',
  animals: '动物',
  art: '艺术与创作',
  books: '书籍与阅读',
  business: '商业与消费',
  cities: '城市生活',
  communication: '沟通与语言',
  culture: '文化与传统',
  education: '教育与学习',
  environment: '环境与自然',
  family: '家庭与关系',
  food: '饮食与健康',
  friends: '朋友与社交',
  geography: '自然地理',
  government: '政府与公共事务',
  health: '健康与生活方式',
  history: '历史与文明',
  home: '家与居住',
  hometown: '家乡',
  media: '媒体与传播',
  people: '人物',
  place: '地点与旅行',
  project: '项目与经历',
  science: '科学探索',
  skill: '技能与成长',
  society: '社会议题',
  sports: '运动与休闲',
  study: '学习与课程',
  technology: '科技与生活',
  tourism: '旅游',
  transport: '交通出行',
  travel: '旅行',
  work: '工作与职业',
}

const QUESTION_TYPE_LABELS: Record<string, string> = {
  task1: 'Task 1',
  task2: 'Task 2',
  true_false_not_given: '判断题',
  yes_no_not_given: '观点判断',
  multiple_choice: '选择题',
  sentence_completion: '句子填空',
  summary_completion: '摘要填空',
  note_completion: '笔记填空',
  table_completion: '表格填空',
  flow_chart_completion: '流程图填空',
  diagram_label_completion: '图示填空',
  matching_headings: '段落标题匹配',
  matching_information: '信息匹配',
  matching_features: '特征匹配',
  matching_sentence_endings: '句尾匹配',
  short_answer: '简答题',
}

export type PracticeFilter = {
  key: string
  label: string
}

export const PRACTICE_FILTERS: Record<string, PracticeFilter[]> = {
  reading: [
    { key: 'all', label: '全部篇章' },
    { key: 'judgement', label: '判断题' },
    { key: 'choice', label: '选择题' },
    { key: 'completion', label: '填空题' },
    { key: 'matching', label: '匹配题' },
  ],
  writing: [
    { key: 'all', label: '全部写作' },
    { key: 'task1', label: 'Task 1 图表写作' },
    { key: 'task2', label: 'Task 2 议论文' },
  ],
  speaking: [
    { key: 'all', label: '全部口语' },
    { key: 'part1', label: 'Part 1 日常问答' },
    { key: 'part2', label: 'Part 2 个人陈述' },
    { key: 'part3', label: 'Part 3 深入讨论' },
  ],
}

export function questionTypeLabel(value?: string | null) {
  if (!value) return '练习'
  return QUESTION_TYPE_LABELS[value] ?? value.replaceAll('_', ' ')
}

export function questionMatchesFilter(question: Question, filter: string) {
  if (!filter || filter === 'all') return true
  if (question.module === 'writing') return question.task === filter
  if (question.module === 'speaking') return `part${question.part}` === filter
  if (question.module !== 'reading') return true

  const type = question.question_type ?? ''
  if (filter === 'judgement') {
    return ['true_false_not_given', 'yes_no_not_given'].includes(type)
  }
  if (filter === 'choice') return type === 'multiple_choice'
  if (filter === 'completion') {
    return type.includes('completion') || type === 'short_answer'
  }
  if (filter === 'matching') return type.startsWith('matching_')
  return true
}

export function questionDisplayTitle(question: Question) {
  const explicit = cleanTitle(question.title)
  if (explicit) return explicit

  if (question.module === 'reading') {
    return cleanTitle(question.passage_title)
      || topicTitle(question.topics_text, '学术阅读')
  }
  if (question.module === 'writing') {
    return writingPromptTitle(question.content, question.task)
  }
  if (question.module === 'speaking') {
    return topicTitle(question.topics_text, `Part ${question.part ?? ''} 口语话题`)
  }
  return topicTitle(question.topics_text, '听力场景练习')
}

export function questionSummary(question: Question) {
  if (question.module === 'reading') {
    return '完整原文与同篇题目会在工作区内并排打开。'
  }
  const compact = compactText(question.content)
    .replace(/^WRITING TASK [12]\s*/i, '')
    .replace(/^PART [123]\s*/i, '')
  return truncate(compact, 150)
}

export function speakingTopicKey(question: Question) {
  return firstTopic(question.topics_text) || 'general'
}

function writingPromptTitle(content: string, task?: string | null) {
  const compact = compactText(content)
  const sentences = compact.split(/(?<=[.!?])\s+/)
  const useful = sentences.find((sentence) => (
    sentence.length > 24
    && !/^WRITING TASK/i.test(sentence)
    && !/^You should spend/i.test(sentence)
    && !/^Write at least/i.test(sentence)
    && !/^Write about the following topic/i.test(sentence)
    && !/^Give reasons for your answer/i.test(sentence)
    && !/^Summarise the information/i.test(sentence)
  ))

  if (!useful) return task === 'task1' ? 'Academic Task 1 写作' : 'Academic Task 2 写作'

  const simplified = useful
    .replace(/^The (?:chart|graph|table|diagram|map|maps|plans?|illustrations?) (?:below|above) (?:shows?|illustrates?|gives? information about)\s*/i, '')
    .replace(/^The (?:chart|graph|table|diagram|map|maps|plans?|illustrations?) (?:shows?|illustrates?)\s*/i, '')
    .replace(/^Some people (?:think|believe|say|argue) that\s*/i, '')
    .replace(/^It is (?:often )?(?:thought|believed|argued) that\s*/i, '')
  return sentenceCase(truncate(simplified, 96))
}

function topicTitle(value: string | null | undefined, fallback: string) {
  const keys = topicKeys(value)
  if (!keys.length) return fallback
  return keys.slice(0, 2).map((key) => TOPIC_LABELS[key] ?? sentenceCase(key)).join(' · ')
}

function firstTopic(value: string | null | undefined) {
  return topicKeys(value)[0] ?? ''
}

function topicKeys(value: string | null | undefined) {
  if (!value) return []
  const normalized = value.trim()
  if (!normalized) return []
  if (normalized.startsWith('[')) {
    try {
      const parsed = JSON.parse(normalized) as unknown
      if (Array.isArray(parsed)) return parsed.map(String).map(cleanTopic).filter(Boolean)
    } catch {
      // Fall through to delimiter parsing for imperfect imported metadata.
    }
  }
  return normalized.split(/[,;|/·\s]+/).map(cleanTopic).filter(Boolean)
}

function cleanTopic(value: string) {
  return value.trim().toLowerCase().replaceAll('_', ' ')
}

function cleanTitle(value: string | null | undefined) {
  const title = compactText(value ?? '')
  if (!title) return ''
  if (/^(READING PASSAGE|WRITING TASK|QUESTIONS?\s+\d+)/i.test(title)) return ''
  if (/^Passage\s+\d+\s+(?:below|above)\b/i.test(title)) return ''
  if (/^Academic Reading\s*[-–—:]/i.test(title)) return ''
  if (/^You should spend about/i.test(title)) return ''
  return truncate(title, 110)
}

function compactText(value: string) {
  return value.replace(/\s+/g, ' ').trim()
}

function truncate(value: string, length: number) {
  if (value.length <= length) return value
  return `${value.slice(0, length).replace(/[\s,;:–—-]+$/g, '')}…`
}

function sentenceCase(value: string) {
  if (!value) return value
  return value.charAt(0).toUpperCase() + value.slice(1)
}
