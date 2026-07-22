import { useMutation, useQuery } from '@tanstack/react-query'
import { BookOpen, PenLine } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api, idempotencyKey, jsonBody, type Question, type SessionSummary } from '../api/client'
import { ErrorState, LoadingState, PageHeader } from '../components/Common'

export function PracticePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const module = searchParams.get('module') ?? 'writing'
  const navigate = useNavigate()
  const questions = useQuery({
    queryKey: ['questions', module],
    queryFn: () => api<Question[]>(`/api/v1/questions?module=${module}&limit=24`),
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
      }),
    }),
    onSuccess: (session) => navigate(`/practice/${module}/${session.session_id}`),
  })
  return (
    <div className="page">
      <PageHeader eyebrow="Practice" title="选择练习" description="明确操作直接进入对应模块，不消耗模型进行重复路由。" />
      <div className="segmented" role="group" aria-label="练习科目">
        <button className={module === 'writing' ? 'active' : ''} onClick={() => setSearchParams({ module: 'writing' })}><PenLine size={17} />Writing</button>
        <button className={module === 'reading' ? 'active' : ''} onClick={() => setSearchParams({ module: 'reading' })}><BookOpen size={17} />Reading</button>
      </div>
      {questions.isPending && <LoadingState />}
      {questions.isError && <ErrorState error={questions.error} />}
      {create.isError && <ErrorState error={create.error} />}
      <div className="question-list">
        {questions.data?.map((question) => (
          <article key={question.question_id} className="question-row">
            <div className="question-meta"><span>{question.task ?? question.question_type ?? module}</span><span>{question.question_id}</span></div>
            <h2>{question.content}</h2>
            <div className="row-actions">
              {module === 'reading' && <button className="button secondary" onClick={() => create.mutate({ question, mode: 'timed-practice' })}>严格计时</button>}
              <button className="button primary" onClick={() => create.mutate({ question })} disabled={create.isPending}>开始练习</button>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}

