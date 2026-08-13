import { useQuery } from '@tanstack/react-query'
import { ArrowRight, BookOpenCheck, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, type ReviewTask, type VocabularyItem } from '../api/client'

/** Today reminder strip shown above the composer: due reviews and words. */
export function TodayReminderStrip() {
  const dueReviews = useQuery({
    queryKey: ['review-tasks', 'due'],
    queryFn: () => api<ReviewTask[]>('/api/v1/review-tasks?status=pending&limit=10'),
    staleTime: 60_000,
  })
  const dueWords = useQuery({
    queryKey: ['vocabulary', 'due'],
    queryFn: () => api<VocabularyItem[]>('/api/v1/vocabulary/due?limit=10'),
    staleTime: 60_000,
  })
  const reviewCount = dueReviews.data?.length ?? 0
  const wordCount = dueWords.data?.length ?? 0

  if (!reviewCount && !wordCount) {
    return (
      <section className="today-reminder-strip quiet" aria-label="今日提醒">
        <BookOpenCheck size={16} aria-hidden="true" />
        <span>今天没有到期的复习任务。有不懂的英文就直接在对话里问。</span>
      </section>
    )
  }
  return (
    <section className="today-reminder-strip" aria-label="今日提醒">
      <Sparkles size={16} aria-hidden="true" />
      <span>
        {wordCount > 0 && (
          <Link to="/vocabulary"><strong>{wordCount} 个单词</strong> 到期复习</Link>
        )}
        {wordCount > 0 && reviewCount > 0 && <span className="reminder-separator">·</span>}
        {reviewCount > 0 && (
          <Link to="/history#review"><strong>{reviewCount} 项</strong> 学习复习到期</Link>
        )}
      </span>
      <Link className="today-reminder-action" to="/history">去复习 <ArrowRight size={14} /></Link>
    </section>
  )
}
