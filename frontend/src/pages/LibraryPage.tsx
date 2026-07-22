import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Question } from '../api/client'
import { ErrorState, LoadingState, PageHeader, StatusBadge } from '../components/Common'

export function LibraryPage() {
  const [module, setModule] = useState('')
  const [query, setQuery] = useState('')
  const questions = useQuery({
    queryKey: ['library', module, query],
    queryFn: () => api<Question[]>(`/api/v1/questions?limit=100${module ? `&module=${module}` : ''}${query ? `&query=${encodeURIComponent(query)}` : ''}`),
  })
  return (
    <div className="page">
      <PageHeader eyebrow="Library" title="本地题库" description="这里只展示已登记来源的题目，不把本地目录当作文件浏览器。" />
      <div className="filter-bar">
        <label>科目<select value={module} onChange={(event) => setModule(event.target.value)}><option value="">全部</option><option value="writing">Writing</option><option value="reading">Reading</option><option value="speaking">Speaking</option></select></label>
        <label>搜索<input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="主题或题目内容" /></label>
      </div>
      {questions.isPending && <LoadingState />}
      {questions.isError && <ErrorState error={questions.error} />}
      <div className="library-grid">
        {questions.data?.map((question) => (
          <article className="library-item" key={question.question_id}>
            <div className="question-meta"><StatusBadge>{question.source_type ?? 'unknown'}</StatusBadge><span>{question.question_id}</span></div>
            <h2>{question.content}</h2>
            <p>{question.module} · {question.task ?? question.question_type ?? 'practice'}</p>
          </article>
        ))}
      </div>
    </div>
  )
}

