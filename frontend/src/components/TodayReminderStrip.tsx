import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Sparkles } from 'lucide-react'
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
    return null
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
