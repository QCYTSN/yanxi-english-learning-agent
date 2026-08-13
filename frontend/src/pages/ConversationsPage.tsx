import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  MessageSquareText,
  Paperclip,
  Plus,
  Search,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type StudyThread } from '../api/client'
import { ErrorState, LoadingState } from '../components/Common'
import { ThreadActions } from '../components/ThreadActions'
import { TodayReminderStrip } from '../components/TodayReminderStrip'

export function ConversationsPage() {
  const [query, setQuery] = useState('')
  const threads = useQuery({
    queryKey: ['study-threads', 'all'],
    queryFn: () => api<StudyThread[]>('/api/v1/study-threads?limit=100'),
  })
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    if (!needle) return threads.data ?? []
    return (threads.data ?? []).filter((thread) => (
      thread.title.toLocaleLowerCase().includes(needle)
      || thread.last_message_preview.toLocaleLowerCase().includes(needle)
    ))
  }, [query, threads.data])

  return (
    <div className="conversation-history-page">
      <header className="conversation-history-header">
        <div>
          <p className="eyebrow">LOCAL STUDY MEMORY</p>
          <h1>学习对话</h1>
          <p>每次提问、追问和上传材料都保存在本机，可以随时回来继续。</p>
        </div>
        <Link className="button primary" to="/today">
          <Plus size={17} />
          新对话
        </Link>
      </header>

      <TodayReminderStrip />

      <label className="conversation-search">
        <Search size={17} aria-hidden="true" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索标题或最近一条消息"
        />
      </label>

      {threads.isPending && <LoadingState label="正在读取本地对话" />}
      {threads.isError && <ErrorState error={threads.error} />}
      {!threads.isPending && !threads.isError && (
        <section className="conversation-history-list" aria-label="全部学习对话">
          {filtered.map((thread) => (
            <article className="conversation-history-row" key={thread.thread_id}>
              <Link
                className="conversation-history-link"
                to={`/study/${thread.thread_id}`}
              >
                <span className="conversation-history-icon">
                  <MessageSquareText size={19} strokeWidth={1.55} aria-hidden="true" />
                </span>
                <span className="conversation-history-copy">
                  <span className="conversation-history-title">
                    <strong>{thread.title}</strong>
                    <time dateTime={thread.updated_at}>{formatThreadDate(thread.updated_at)}</time>
                  </span>
                  <span className="conversation-history-preview">
                    {thread.last_message_preview || '尚无对话内容'}
                  </span>
                  <span className="conversation-history-meta">
                    {moduleLabel(thread.module)}
                    <span>{thread.message_count} 条消息</span>
                    {thread.attachment_count > 0 && (
                      <span><Paperclip size={12} />{thread.attachment_count} 份材料</span>
                    )}
                  </span>
                </span>
                <ArrowRight className="conversation-history-arrow" size={18} aria-hidden="true" />
              </Link>
              <ThreadActions thread={thread} />
            </article>
          ))}
          {!filtered.length && (
            <div className="conversation-history-empty">
              <MessageSquareText size={24} strokeWidth={1.4} />
              <strong>{query ? '没有匹配的对话' : '还没有学习对话'}</strong>
              <p>{query ? '换一个关键词试试。' : '从首页问一个问题，第一段学习记录就会出现在这里。'}</p>
            </div>
          )}
        </section>
      )}
    </div>
  )
}

function moduleLabel(module: StudyThread['module']) {
  const labels: Record<StudyThread['module'], string> = {
    listening: '听力',
    reading: '阅读',
    writing: '写作',
    speaking: '口语',
    mixed: '综合',
  }
  return labels[module]
}

function formatThreadDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    year: date.getFullYear() === new Date().getFullYear() ? undefined : 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}
