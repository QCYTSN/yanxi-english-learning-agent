import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpen, Headphones, Mic2, PenLine, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type AssessmentPack, type AssessmentRun, type Question, type SessionSummary } from '../api/client'
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
  speaking: { label: 'Speaking', name: '口语', icon: Mic2, summary: 'Voice / Live 模考任务包与报告导回', boundary: '完整模考中不中途纠错；结束后再导入转写或结构化报告。' },
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
  const packs = useQuery({
    queryKey: ['assessment-packs', module],
    queryFn: () => api<AssessmentPack[]>(`/api/v1/assessment-packs?module=${module}&practice_mode=full_mock&conformance_status=verified&limit=24`),
  })
  const startMock = useMutation({
    mutationFn: (packId: string) => api<AssessmentRun>('/api/v1/assessment-runs', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({ pack_id: packId, practice_unit_id: practiceUnitId }),
    }),
    onSuccess: (run) => navigate(`/assessment/${run.run_id}`),
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
        eyebrow="Practice · 练习中心"
        title="按科目进入正式学习流程"
        description="系统直接打开对应学习模块；只有解释、反馈和评价等任务才会交给当前 AI。"
        action={<Link className="button secondary" to="/library"><ShieldCheck size={17} />查看内容合规状态</Link>}
      />
      <section className="practice-console">
        <aside className="practice-module-index">
          <p className="eyebrow">选择科目</p>
          <ModuleTabs module={module} setModule={chooseModule} />
          <div className="practice-boundary">
            <span>训练规则</span>
            <p>{moduleMeta.boundary}</p>
          </div>
        </aside>
        <div className="practice-catalog">
          <header className="catalog-heading">
            <div className="catalog-icon"><ModuleIcon size={24} strokeWidth={1.7} /></div>
            <div><p>{moduleMeta.name}</p><h2>{moduleMeta.label}</h2><span>{moduleMeta.summary}</span></div>
          </header>

          <FullMockPacks packs={packs.data ?? []} pending={packs.isPending} startMock={(packId) => startMock.mutate(packId)} starting={startMock.isPending} />
          {packs.isError && <ErrorState error={packs.error} />}
          {startMock.isError && <ErrorState error={startMock.error} />}

          {module === 'listening' ? (
            <section className="workspace-entry">
              <div>
                <p className="eyebrow">{moduleMeta.name}工作区</p>
                <h2>进入高频场景听辨语料库</h2>
                <p>按场景听写高频表达，记录拼写、定位与干扰项错因。</p>
              </div>
              <button className="button primary" onClick={() => navigate(`/practice/${module}${practiceUnitId ? `?practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)}>
                进入工作区 <ArrowRight size={17} />
              </button>
            </section>
          ) : (
            <>
              {module === 'speaking' && (
                <section className="workspace-entry">
                  <div>
                    <p className="eyebrow">口语工作区</p>
                    <h2>选择 Part 和话题，再交给 Voice / Live 主持</h2>
                    <p>系统负责选题、流程与复盘；外部语音页面负责真实口语互动。</p>
                  </div>
                  <button
                    className="button primary"
                    onClick={() => {
                      const mode = category.startsWith('part') ? category : 'full_mock'
                      navigate(`/practice/speaking?mode=${mode}${practiceUnitId ? `&practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)
                    }}
                  >
                    进入口语工作区 <ArrowRight size={17} />
                  </button>
                </section>
              )}
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
                <div><p className="eyebrow">练习目录</p><h2>按主题选择想学的内容</h2></div>
                <span>{displayUnits.length} {module === 'reading' ? '篇' : '项'}可见内容</span>
              </div>
              {questions.isPending && <LoadingState />}
              {questions.isError && <ErrorState error={questions.error} />}
              {create.isError && <ErrorState error={create.error} />}
              {!questions.isPending && displayUnits.length === 0 && (
                <EmptyState title="这个分类暂时没有可用练习">
                  可以切换其他分类，或先到内容题库导入和审核自有材料。
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
                      </div>
                      <h2>{title}</h2>
                      <p className="question-summary">{questionSummary(question)}</p>
                      <ConformanceBadge status={question.conformance_status} mode={question.practice_mode} />
                    </div>
                    <div className="row-actions question-actions">
                      {module === 'reading' && <button className="button secondary" onClick={() => create.mutate({ question, mode: 'timed-practice' })} disabled={question.conformance_status === 'rejected'}>20 分钟计时</button>}
                      {module === 'speaking'
                        ? <button
                            className="button primary"
                            onClick={() => {
                              const ids = unit.questionIds.join(',')
                              navigate(`/practice/speaking?mode=part${question.part}&question_ids=${encodeURIComponent(ids)}${practiceUnitId ? `&practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)
                            }}
                          >
                            练习本组 <ArrowRight size={16} />
                          </button>
                        : <button className="button primary" onClick={() => create.mutate({ question })} disabled={create.isPending || question.conformance_status === 'rejected'}>{module === 'reading' ? '引导练习' : '开始写作'} <ArrowRight size={16} /></button>}
                    </div>
                  </article>
                )})}
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
        </div>
      </section>
    </div>
  )
}

function FullMockPacks({ packs, pending, startMock, starting }: { packs: AssessmentPack[]; pending: boolean; startMock: (packId: string) => void; starting: boolean }) {
  const approved = packs.filter((pack) => pack.local_review_status === 'approved')
  if (!pending && approved.length === 0) return null
  return <section className="mock-pack-section">
    <div className="section-heading">
      <div><p className="eyebrow">整套练习</p><h2>经审核的考试流程</h2></div>
      <p>只有结构合规并通过本地审核的套题才能启动；题目、计时和作答会冻结在同一次运行中。</p>
    </div>
    {pending && <LoadingState label="正在检查可用套题" />}
    <div className="mock-pack-grid">
      {approved.map((pack) => <article key={pack.pack_id} className="mock-pack-card">
        <div><span className="status-dot" />正式运行</div>
        <h3>{pack.title}</h3>
        <p>{MODULES[pack.module]?.name ?? 'IELTS'} · 内容已审核</p>
        <button className="button primary" disabled={starting} onClick={() => startMock(pack.pack_id)}>启动完整模考</button>
      </article>)}
    </div>
  </section>
}

function ModuleTabs({ module, setModule }: { module: string; setModule: (module: string) => void }) {
  return <div className="module-tabs" role="group" aria-label="练习科目">
    {Object.entries(MODULES).map(([key, item]) => {
      const Icon = item.icon
      return <button className={module === key ? 'active' : ''} key={key} onClick={() => setModule(key)} type="button"><Icon size={18} /><span><strong>{item.label}</strong><small>{item.name}</small></span><ArrowRight size={15} /></button>
    })}
  </div>
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
