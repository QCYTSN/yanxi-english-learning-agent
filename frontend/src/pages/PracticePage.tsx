import { useMutation, useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  BookMarked,
  BookOpen,
  Headphones,
  Keyboard,
  Mic2,
  PenLine,
  Volume2,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type Question, type SessionSummary } from '../api/client'
import { ConformanceBadge, EmptyState, ErrorState, LoadingState, PageHeader } from '../components/Common'
import {
  PRACTICE_FILTERS,
  questionDisplayTitle,
  questionMatchesFilter,
  questionSummary,
  questionTypeLabel,
  speakingTopicKey,
} from '../questionPresentation'

const MODULES = {
  writing: { label: 'Writing', name: '写作', icon: PenLine, summary: '独立作答、证据化估分与主动修订', boundary: '反馈按证据与评分标准组织；学习者先完成 V2，之后才显示模型替代版本。' },
  reading: { label: 'Reading', name: '阅读', icon: BookOpen, summary: '完整篇章、题型专项与逐级提示', boundary: '引导练习先给定位提示，再开放答案；解释必须回到原文证据。' },
  listening: { label: 'Listening', name: '听力', icon: Headphones, summary: '高频场景语料与间隔复习', boundary: '先听辨和输入，再核对答案与错因；场景表达进入统一复习队列。' },
  speaking: { label: 'Speaking', name: '口语', icon: Mic2, summary: '两步口语练习：领场景任务、贴回转写点评', boundary: '练习过程中不中途纠错；练完贴回转写，再从清晰度、自然度和语法三方面点评。' },
} as const

export function PracticePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const module = searchParams.get('module') ?? 'writing'
  const category = searchParams.get('type') ?? 'all'
  const practiceUnitId = searchParams.get('practice_unit_id')
  const navigate = useNavigate()
  const [visibleLimit, setVisibleLimit] = useState(12)
  const questions = useQuery({
    queryKey: ['questions', module],
    queryFn: () => api<Question[]>(`/api/v1/questions?module=${module}&limit=500`),
  })
  const create = useMutation({
    mutationFn: async ({ question, mode }: { question: Question; mode?: string }) => api<SessionSummary>('/api/v1/sessions', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({
        module,
        question_id: question.question_id,
        passage_id: question.passage_id ?? null,
        mode: mode ?? (module === 'reading' ? 'guided-solving' : 'timed-practice'),
        practice_unit_id: practiceUnitId,
      }),
    }),
    onSuccess: (session) => navigate(`/practice/${module}/${session.session_id}`),
  })
  const moduleMeta = MODULES[module as keyof typeof MODULES] ?? MODULES.writing
  const ModuleIcon = moduleMeta.icon
  const visibleQuestions = (questions.data ?? []).filter(
    (question) => questionMatchesFilter(question, category),
  )
  const displayUnits = module === 'reading'
    ? groupReadingQuestions(visibleQuestions)
    : module === 'speaking'
      ? groupSpeakingQuestions(visibleQuestions)
      : visibleQuestions.map((question) => ({
        key: question.question_id,
        question,
        count: 1,
        types: [question.task ?? question.question_type ?? module],
        questionIds: [question.question_id],
      }))
  const filters = PRACTICE_FILTERS[module] ?? []
  const visibleUnits = displayUnits.slice(0, visibleLimit)

  useEffect(() => {
    setVisibleLimit(12)
  }, [module, category])

  function chooseModule(value: string) {
    const next = new URLSearchParams()
    next.set('module', value)
    if (practiceUnitId) next.set('practice_unit_id', practiceUnitId)
    setSearchParams(next)
  }

  function chooseCategory(value: string) {
    const next = new URLSearchParams(searchParams)
    if (value === 'all') next.delete('type')
    else next.set('type', value)
    setSearchParams(next)
  }

  return (
    <div className="page page-practice">
      <PageHeader
        eyebrow="练习中心"
        title="选择科目与专项练习"
        description="按四科题库进行证据化训练，或使用下方的听言与打词微练习强化词汇记忆。"
      />

      {/* 微练习快捷工具条 */}
      <section className="practice-quick-drills" aria-label="微练习与词表">
        <span className="quick-drills-label">专项微练习：</span>
        <Link className="quick-drill-chip" to="/practice/typing">
          <Keyboard size={15} />
          <span>打字练习</span>
        </Link>
        <Link className="quick-drill-chip" to="/practice/listen">
          <Volume2 size={15} />
          <span>听言练习</span>
        </Link>
        <Link className="quick-drill-chip" to="/vocabulary">
          <BookMarked size={15} />
          <span>我的词表</span>
        </Link>
        <Link className="quick-drill-chip" to="/today">
          <PenLine size={15} />
          <span>自由向老师提问</span>
        </Link>
      </section>

      {/* 四科核心大卡片选择器 */}
      <section className="practice-module-deck" aria-label="选择练习科目">
        {Object.entries(MODULES).map(([key, item]) => {
          const Icon = item.icon
          const isSelected = module === key
          return (
            <button
              key={key}
              type="button"
              className={`practice-module-card${isSelected ? ' active' : ''}`}
              onClick={() => chooseModule(key)}
              aria-pressed={isSelected}
            >
              <div className="module-card-head">
                <span className="module-card-icon">
                  <Icon size={20} strokeWidth={1.8} />
                </span>
                <span className="module-card-titles">
                  <strong>{item.name}</strong>
                  <small>{item.label}</small>
                </span>
              </div>
              <p className="module-card-summary">{item.summary}</p>
            </button>
          )
        })}
      </section>

      {/* 当前科目练习工作区 */}
      <section className="practice-workbench-section">
        <header className="practice-workbench-header">
          <div className="workbench-title-group">
            <span className="workbench-icon"><ModuleIcon size={20} /></span>
            <div>
              <h2>{moduleMeta.name} · {moduleMeta.label} 练习</h2>
              <small className="workbench-boundary">{moduleMeta.boundary}</small>
            </div>
          </div>
        </header>

        {module === 'listening' ? (
          <section className="workspace-entry-card">
            <div className="entry-card-copy">
              <p className="eyebrow">{moduleMeta.name}工作区</p>
              <h2>进入高频场景听辨语料库</h2>
              <p>按场景听写高频表达，系统自动记录拼写、定位与干扰项错因，生成复习队列。</p>
            </div>
            <button
              className="button primary"
              type="button"
              onClick={() => navigate(`/practice/${module}${practiceUnitId ? `?practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)}
            >
              <Headphones size={17} />
              进入听辨工作区 <ArrowRight size={17} />
            </button>
          </section>
        ) : (
          <>
            {module === 'speaking' && (
              <section className="workspace-entry-card speaking-entry">
                <div className="entry-card-copy">
                  <p className="eyebrow">口语工作区</p>
                  <h2>选择 Part 和话题，由外部语音页面完成主持</h2>
                  <p>言蹊负责选题、流程与标准复盘；你可以使用顺手的语音工具开口练习，再带回转写点评。</p>
                </div>
                <button
                  className="button primary"
                  type="button"
                  onClick={() => {
                    const mode = category.startsWith('part') ? category : 'full_mock'
                    navigate(`/practice/speaking?mode=${mode}${practiceUnitId ? `&practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)
                  }}
                >
                  <Mic2 size={17} />
                  进入口语工作区 <ArrowRight size={17} />
                </button>
              </section>
            )}

            {/* 题型胶囊过滤器 */}
            {filters.length > 0 && (
              <div className="practice-filters" role="group" aria-label={`${moduleMeta.name}练习分类`}>
                {filters.map((filter) => (
                  <button
                    className={category === filter.key || (category === 'all' && filter.key === 'all') ? 'active' : ''}
                    key={filter.key}
                    onClick={() => chooseCategory(filter.key)}
                    type="button"
                  >
                    {filter.label}
                  </button>
                ))}
              </div>
            )}

            <div className="catalog-section-heading">
              <div>
                <h2>{category === 'all' ? '全部题目' : filters.find(f => f.key === category)?.label ?? '题目列表'}</h2>
              </div>
              <span>共 {displayUnits.length} {module === 'reading' ? '篇' : '项'}练习</span>
            </div>

            {questions.isPending && <LoadingState label="正在载入题库" />}
            {questions.isError && <ErrorState error={questions.error} />}
            {create.isError && <ErrorState error={create.error} />}
            {!questions.isPending && displayUnits.length === 0 && (
              <EmptyState title="这个分类暂时没有可用练习">
                可以切换其他分类，或先到资料库导入自有材料。
              </EmptyState>
            )}

            <div className="question-list">
              {visibleUnits.map((unit) => {
                const question = unit.question
                const title = questionDisplayTitle(question)
                return (
                  <article key={unit.key} className="question-row">
                    <span className="question-kind-icon">
                      {module === 'writing' ? <PenLine size={18} /> : module === 'speaking' ? <Mic2 size={18} /> : <BookOpen size={18} />}
                    </span>
                    <div className="question-body">
                      <div className="question-meta">
                        <span>
                          {module === 'speaking'
                            ? `Part ${question.part} · ${unit.count} 个问题`
                            : module === 'reading'
                              ? `${unit.count} 题 · ${unit.types.map(questionTypeLabel).join(' / ')}`
                              : questionTypeLabel(question.task ?? question.question_type ?? module)}
                        </span>
                        <ConformanceBadge status={question.conformance_status} mode={question.practice_mode} />
                      </div>
                      <h2>{title}</h2>
                      <p className="question-summary">{questionSummary(question)}</p>
                    </div>
                    <div className="row-actions question-actions">
                      {module === 'reading' && (
                        <button
                          className="button secondary"
                          onClick={() => create.mutate({ question, mode: 'timed-practice' })}
                          disabled={question.conformance_status === 'rejected'}
                        >
                          20 分钟计时
                        </button>
                      )}
                      {module === 'speaking' ? (
                        <button
                          className="button primary"
                          onClick={() => {
                            const ids = unit.questionIds.join(',')
                            navigate(`/practice/speaking?mode=part${question.part}&question_ids=${encodeURIComponent(ids)}${practiceUnitId ? `&practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)
                          }}
                        >
                          练习本组 <ArrowRight size={16} />
                        </button>
                      ) : (
                        <button
                          className="button primary"
                          onClick={() => create.mutate({ question })}
                          disabled={create.isPending || question.conformance_status === 'rejected'}
                        >
                          {module === 'reading' ? '引导练习' : '开始写作'} <ArrowRight size={16} />
                        </button>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>

            {visibleUnits.length < displayUnits.length && (
              <button
                className="catalog-load-more"
                type="button"
                onClick={() => setVisibleLimit((value) => value + 12)}
              >
                再显示 12 项
                <span>还有 {displayUnits.length - visibleUnits.length} 项</span>
              </button>
            )}
          </>
        )}
      </section>
    </div>
  )
}

type DisplayUnit = {
  key: string
  question: Question
  count: number
  types: string[]
  questionIds: string[]
}

function groupReadingQuestions(questions: Question[]): DisplayUnit[] {
  const groups = new Map<string, DisplayUnit>()
  questions.forEach((question) => {
    const key = question.passage_id ?? question.question_id
    const current = groups.get(key)
    const type = question.question_type ?? 'reading'
    if (current) {
      current.count += 1
      current.questionIds.push(question.question_id)
      if (!current.types.includes(type)) current.types.push(type)
      return
    }
    groups.set(key, { key, question, count: 1, types: [type], questionIds: [question.question_id] })
  })
  return Array.from(groups.values())
}

function groupSpeakingQuestions(questions: Question[]): DisplayUnit[] {
  const groups = new Map<string, DisplayUnit>()
  questions.forEach((question) => {
    const key = `${question.part ?? 'x'}:${speakingTopicKey(question)}`
    const current = groups.get(key)
    if (current) {
      current.count += 1
      current.questionIds.push(question.question_id)
      return
    }
    groups.set(key, {
      key,
      question,
      count: 1,
      types: [`part${question.part ?? ''}`],
      questionIds: [question.question_id],
    })
  })
  return Array.from(groups.values())
}
