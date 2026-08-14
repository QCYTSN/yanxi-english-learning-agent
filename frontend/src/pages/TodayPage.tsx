import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowRight,
  BookOpenText,
  Clock3,
  Headphones,
  Lightbulb,
  Mic2,
  PenLine,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import {
  api,
  jsonBody,
  type Bootstrap,
  type LearningModelSnapshot,
  type PracticeUnit,
  type StudyContext,
  type TeachingCycle,
} from '../api/client'
import { ErrorState } from '../components/Common'
import { LearningCycleStrip } from '../components/LearningCycleStrip'
import { MaterialComposer } from '../components/MaterialComposer'
import { TodayReminderStrip } from '../components/TodayReminderStrip'
import { dimensionLabel, objectiveStatusLabel } from '../learningPresentation'
import { createStudyThreadWithMessage, requestRemoteProcessingConsent } from '../studyThreads'

const subjects = [
  { module: 'listening', label: '听力', icon: Headphones },
  { module: 'reading', label: '阅读', icon: BookOpenText },
  { module: 'writing', label: '写作', icon: PenLine },
  { module: 'speaking', label: '口语', icon: Mic2 },
] as const

export function TodayPage({ bootstrap }: { bootstrap: Bootstrap }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const active = bootstrap.active_session
  const primary = bootstrap.model_providers.find(
    (item) => item.role === 'primary' && item.is_enabled,
  )
  const context = useQuery({
    queryKey: ['today-context'],
    queryFn: () => api<StudyContext>('/api/v1/today'),
  })
  const learningModel = useQuery({
    queryKey: ['learning-model'],
    queryFn: () => api<LearningModelSnapshot>('/api/v1/learning-model'),
    staleTime: 30_000,
  })
  const teachingCycles = useQuery({
    queryKey: ['teaching-cycles', 'active'],
    queryFn: () => api<TeachingCycle[]>('/api/v1/teaching-cycles?status=active&limit=10'),
    staleTime: 15_000,
  })
  const ask = useMutation({
    mutationFn: ({ content, files, explicitConsent }: { content: string; files: File[]; explicitConsent: boolean }) => {
      if (!primary) throw new Error('请先连接一个主模型')
      return createStudyThreadWithMessage({
        content,
        files,
        modelProviderId: primary.provider_id,
        explicitConsent,
      })
    },
    onSuccess: async ({ thread, run }) => {
      await queryClient.invalidateQueries({ queryKey: ['study-threads'] })
      navigate(`/study/${thread.thread_id}?run=${run.run_id}`)
    },
  })
  const materialise = useMutation({
    mutationFn: () => api<PracticeUnit>('/api/v1/today/materialise', {
      method: 'POST',
      body: jsonBody({ slot: 'primary' }),
    }),
    onSuccess: (unit) => navigate(unit.launch_url),
  })

  const recommendation = context.data?.today_plan.primary
  const currentCycle = teachingCycles.data?.[0]
  const currentObjective = learningModel.data?.objectives.find((item) => item.status === 'active')
    ?? learningModel.data?.objectives.find((item) => item.status === 'planned')
  const actionError = ask.error ?? materialise.error ?? context.error

  return (
    <div className="today-start-page">
      <TodayReminderStrip />
      <section className="learning-launcher" aria-labelledby="today-question">
        <header className="launcher-heading">
          <h1 id="today-question">今天想弄懂什么？</h1>
          <p>直接和英语老师交流，或上传题目、原文和作文；材料不是开始对话的前提。</p>
        </header>

        <div className="today-composer-zone">
          <div className="intent-box study-launcher-composer">
            <MaterialComposer
              onSend={async (content, files) => {
                if (!primary) return false
                const explicitConsent = requestRemoteProcessingConsent(primary)
                if (explicitConsent === null) return false
                await ask.mutateAsync({ content, files, explicitConsent })
              }}
              pending={ask.isPending}
              disabled={!primary}
            />
          </div>
          <div className="subject-shortcuts" aria-label="四科快捷入口">
            {subjects.map(({ module, label, icon: Icon }) => (
              <button
                key={module}
                type="button"
                className="subject-shortcut-btn"
                onClick={() => navigate(`/practice?module=${module}`)}
              >
                <Icon size={17} strokeWidth={1.7} aria-hidden="true" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="today-secondary-deck">
          {active ? (
            <Link className="resume-learning-row" to={sessionDestination(active)}>
              <span className="resume-icon"><ModuleGlyph module={active.module} /></span>
              <span className="resume-copy">
                <small>继续上次学习</small>
                <strong>{activeTitle(active.module, active.status)}</strong>
              </span>
              <span className="resume-time"><Clock3 size={15} />进度已保存</span>
              <span className="resume-action">继续 <ArrowRight size={16} /></span>
            </Link>
          ) : recommendation ? (
            <button
              className="resume-learning-row recommendation-row"
              type="button"
              onClick={() => materialise.mutate()}
              disabled={materialise.isPending}
            >
              <span className="resume-icon"><ModuleGlyph module={recommendation.module} /></span>
              <span className="resume-copy">
                <small>今日推荐</small>
                <strong>{recommendation.title}</strong>
              </span>
              <span className="resume-time"><Clock3 size={15} />约 {recommendation.estimated_minutes} 分钟</span>
              <span className="resume-action">开始 <ArrowRight size={16} /></span>
            </button>
          ) : null}

          {currentCycle ? (
            <div className="today-learning-direction">
              <div className="today-learning-direction-heading">
                <span>当前学习方向</span>
                <Link to="/settings/learning">管理目标与记忆</Link>
              </div>
              <LearningCycleStrip cycle={currentCycle} />
            </div>
          ) : currentObjective ? (
            <div className="today-learning-direction objective-only">
              <div className="today-learning-direction-heading">
                <span>当前学习目标</span>
                <Link to="/settings/learning">管理</Link>
              </div>
              <div className="today-objective-line">
                <span>{dimensionLabel(currentObjective.dimension_id)}</span>
                <strong>{currentObjective.title}</strong>
                <small>{objectiveStatusLabel(currentObjective.status)}</small>
              </div>
            </div>
          ) : null}

          <div className="today-guidance">
            <Lightbulb size={17} aria-hidden="true" />
            <p>
              <strong>今日建议：</strong>
              {active
                ? `先完成${moduleLabel(active.module)}练习，再开始新的任务。`
                : recommendation?.reason ?? '先完成一项高价值练习，不必把计划排满。'}
            </p>
          </div>
        </div>

        {!primary && (
          <p className="quiet-connection-note">
            四科练习和本地保存可以直接使用；上传材料并提问前，请先
            <Link to="/settings/models">连接一个主模型</Link>。
          </p>
        )}
        {actionError && <ErrorState error={actionError} />}
      </section>
    </div>
  )
}

function ModuleGlyph({ module }: { module: string }) {
  const Icon = ({
    listening: Headphones,
    reading: BookOpenText,
    writing: PenLine,
    speaking: Mic2,
  } as Record<string, typeof PenLine>)[module] ?? BookOpenText
  return <Icon size={20} strokeWidth={1.65} aria-hidden="true" />
}

function sessionDestination(session: Bootstrap['active_session']) {
  if (!session) return '/today'
  if (session.module === 'speaking') return `/practice/speaking?session=${session.session_id}`
  if (session.module === 'listening') return `/practice/listening/${session.session_id}`
  return `/practice/${session.module}/${session.session_id}`
}

function activeTitle(module: string, status: string) {
  if (module === 'writing' && status === 'awaiting_revision') return 'Writing Task 2 · V2 修改'
  return `${moduleLabel(module)} · ${statusLabel(status)}`
}

function moduleLabel(module: string) {
  return ({
    writing: '写作',
    reading: '阅读',
    speaking: '口语',
    listening: '听力',
  } as Record<string, string>)[module] ?? module
}

function statusLabel(status: string) {
  return ({
    draft: '准备开始',
    learner_working: '继续作答',
    awaiting_feedback: '等待反馈',
    awaiting_revision: '继续修改',
  } as Record<string, string>)[status] ?? '继续学习'
}
