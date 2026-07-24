import { useMutation, useQuery } from '@tanstack/react-query'
import { BookOpen, Headphones, Mic2, PenLine } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type AssessmentPack, type AssessmentRun, type Question, type SessionSummary } from '../api/client'
import { ConformanceBadge, ErrorState, LoadingState, PageHeader } from '../components/Common'

export function PracticePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const module = searchParams.get('module') ?? 'writing'
  const practiceUnitId = searchParams.get('practice_unit_id')
  const navigate = useNavigate()
  const questions = useQuery({
    queryKey: ['questions', module],
    queryFn: () => api<Question[]>(`/api/v1/questions?module=${module}&limit=24`),
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
  if (module === 'speaking' || module === 'listening') {
    return (
      <div className="page">
        <PageHeader eyebrow="Practice" title="选择练习" description="明确操作直接进入对应模块，不消耗模型进行重复路由。" />
        <ModuleTabs module={module} setModule={(value) => setSearchParams({ module: value })} />
        <FullMockPacks packs={packs.data ?? []} pending={packs.isPending} startMock={(packId) => startMock.mutate(packId)} starting={startMock.isPending} />
        {packs.isError && <ErrorState error={packs.error} />}
        {startMock.isError && <ErrorState error={startMock.error} />}
        <section className="primary-card">
          <div><p className="eyebrow">{module}</p><h2>{module === 'speaking' ? 'Voice / Live 外部语音练习' : '高频场景听辨语料'}</h2><p>{module === 'speaking' ? '生成模考任务包，练习后导回转写或结构化报告。' : '通过系统语音听写高频表达，并记录错因和复习状态。'}</p></div>
          <button className="button primary" onClick={() => navigate(`/practice/${module}${practiceUnitId ? `?practice_unit_id=${encodeURIComponent(practiceUnitId)}` : ''}`)}>{module === 'speaking' ? <Mic2 size={18} /> : <Headphones size={18} />}进入工作区</button>
        </section>
      </div>
    )
  }
  return (
    <div className="page">
      <PageHeader eyebrow="Practice" title="选择练习" description="明确操作直接进入对应模块，不消耗模型进行重复路由。" />
      <ModuleTabs module={module} setModule={(value) => setSearchParams({ module: value })} />
      <FullMockPacks packs={packs.data ?? []} pending={packs.isPending} startMock={(packId) => startMock.mutate(packId)} starting={startMock.isPending} />
      {packs.isError && <ErrorState error={packs.error} />}
      {startMock.isError && <ErrorState error={startMock.error} />}
      {questions.isPending && <LoadingState />}
      {questions.isError && <ErrorState error={questions.error} />}
      {create.isError && <ErrorState error={create.error} />}
      <div className="question-list">
        {questions.data?.map((question) => (
          <article key={question.question_id} className="question-row">
            <div className="question-meta"><span>{question.task ?? question.question_type ?? module}</span><span>{question.question_id}</span></div>
            <h2>{question.content}</h2>
            <ConformanceBadge status={question.conformance_status} mode={question.practice_mode} />
            <div className="row-actions">
              {module === 'reading' && <button className="button secondary" onClick={() => create.mutate({ question, mode: 'timed-practice' })} disabled={question.conformance_status === 'rejected'}>20 分钟篇章专项</button>}
              <button className="button primary" onClick={() => create.mutate({ question })} disabled={create.isPending || question.conformance_status === 'rejected'}>开始练习</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}

function FullMockPacks({ packs, pending, startMock, starting }: { packs: AssessmentPack[]; pending: boolean; startMock: (packId: string) => void; starting: boolean }) {
  return <section className="mock-pack-section">
    <div className="section-heading">
      <div><p className="eyebrow">V0.9 Assessment Runner</p><h2>经审核的完整模考</h2></div>
      <p>只有结构合规且已完成本地内容审核的套题才能启动；题目、计时、作答和提交记录会冻结在同一个运行中。</p>
    </div>
    {pending && <LoadingState label="正在检查可用套题" />}
    {!pending && packs.length === 0 && <div className="empty-inline">当前科目暂无可启动的完整套题。请先在题库工作台完成导入、组卷和审核。</div>}
    <div className="mock-pack-grid">
      {packs.filter((pack) => pack.local_review_status === 'approved').map((pack) => <article key={pack.pack_id} className="mock-pack-card">
        <div><span className="status-dot" />正式运行</div>
        <h3>{pack.title}</h3>
        <p>{pack.module.toUpperCase()} · {pack.practice_mode}</p>
        <button className="button primary" disabled={starting} onClick={() => startMock(pack.pack_id)}>启动完整模考</button>
      </article>)}
    </div>
  </section>
}

function ModuleTabs({ module, setModule }: { module: string; setModule: (module: string) => void }) {
  return <div className="segmented module-tabs" role="group" aria-label="练习科目"><button className={module === 'writing' ? 'active' : ''} onClick={() => setModule('writing')}><PenLine size={17} />Writing</button><button className={module === 'reading' ? 'active' : ''} onClick={() => setModule('reading')}><BookOpen size={17} />Reading</button><button className={module === 'speaking' ? 'active' : ''} onClick={() => setModule('speaking')}><Mic2 size={17} />Speaking</button><button className={module === 'listening' ? 'active' : ''} onClick={() => setModule('listening')}><Headphones size={17} />Listening</button></div>
}
