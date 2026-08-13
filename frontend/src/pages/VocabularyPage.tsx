import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookMarked, CalendarClock, CheckCircle2, Plus, Trash2, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { api, jsonBody, type VocabularyItem } from '../api/client'
import { ErrorState, LoadingState, StatusBadge } from '../components/Common'

export function VocabularyPage() {
  const queryClient = useQueryClient()
  const [word, setWord] = useState('')
  const [meaning, setMeaning] = useState('')
  const items = useQuery({
    queryKey: ['vocabulary', 'all'],
    queryFn: () => api<VocabularyItem[]>('/api/v1/vocabulary?limit=500'),
  })
  const due = useQuery({
    queryKey: ['vocabulary', 'due'],
    queryFn: () => api<VocabularyItem[]>('/api/v1/vocabulary/due?limit=50'),
    staleTime: 30_000,
  })
  const ingested = useQuery({
    queryKey: ['vocabulary', 'ingested'],
    queryFn: () => api<VocabularyItem[]>('/api/v1/vocabulary/ingested?limit=20'),
    staleTime: 15_000,
  })
  const add = useMutation({
    mutationFn: () => api<VocabularyItem>('/api/v1/vocabulary', {
      method: 'POST',
      body: jsonBody({ word, meaning: meaning || null }),
    }),
    onSuccess: async () => {
      setWord('')
      setMeaning('')
      await queryClient.invalidateQueries({ queryKey: ['vocabulary'] })
    },
  })
  const schedule = useMutation({
    mutationFn: (itemId: string) => api<VocabularyItem>(`/api/v1/vocabulary/${itemId}/review`, {
      method: 'PATCH',
      body: jsonBody({ days: 3 }),
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vocabulary'] }),
  })
  const setStatus = useMutation({
    mutationFn: ({ itemId, status }: { itemId: string; status: VocabularyItem['status'] }) =>
      api<VocabularyItem>(`/api/v1/vocabulary/${itemId}/status`, {
        method: 'PATCH',
        body: jsonBody({ status }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vocabulary'] }),
  })
  const undoIngest = useMutation({
    mutationFn: (itemId: string) => api<{ item_id: string; removed: boolean }>(
      `/api/v1/vocabulary/ingested/${itemId}/undo`,
      { method: 'POST' },
    ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['vocabulary'] }),
  })
  const dueWords = due.data ?? []
  const allWords = (items.data ?? []).filter((item) => item.status !== 'dismissed' && item.status !== 'candidate')
  const ingestedWords = ingested.data ?? []

  return (
    <div className="vocabulary-page">
      <header className="conversation-history-header">
        <div>
          <p className="eyebrow">MY WORDS</p>
          <h1>我的词表</h1>
          <p>对话里讲过的词会自动收进这里；确认后进入间隔复习，也可以撤销或标记“早认识了”。</p>
        </div>
      </header>

      <section className="vocabulary-add-panel">
        <form
          className="vocabulary-add-form"
          onSubmit={(event) => {
            event.preventDefault()
            if (word.trim()) add.mutate()
          }}
        >
          <label>
            <BookMarked size={16} aria-hidden="true" />
            <input
              value={word}
              onChange={(event) => setWord(event.target.value)}
              placeholder="想记住的英文单词或短语"
            />
          </label>
          <label>
            <input
              value={meaning}
              onChange={(event) => setMeaning(event.target.value)}
              placeholder="释义（可留空，对话里讲过的会自动带上）"
            />
          </label>
          <button className="button primary" type="submit" disabled={!word.trim() || add.isPending}>
            <Plus size={16} />加入词表
          </button>
        </form>
        {add.error && <ErrorState error={add.error} />}
      </section>

      {ingestedWords.length > 0 && (
        <section className="vocabulary-section">
          <h2>对话里讲过的 <StatusBadge tone="warning">{ingestedWords.length}</StatusBadge></h2>
          <p className="muted">这些词是言蹊在对话中讲到的，等你确认：留下进入复习，或标记“早认识了”不再打扰。</p>
          <div className="vocabulary-grid">
            {ingestedWords.map((item) => (
              <article className="vocabulary-card candidate" key={item.item_id}>
                <div className="vocabulary-card-head">
                  <strong>{item.word}</strong>
                  <span>{item.meaning ?? '来自对话讲解'}</span>
                </div>
                {item.example && <p>{item.example}</p>}
                <div className="vocabulary-card-actions">
                  <button
                    className="button secondary"
                    onClick={() => setStatus.mutate({ itemId: item.item_id, status: 'learning' })}
                  >
                    <CheckCircle2 size={15} />收下，安排复习
                  </button>
                  <button
                    className="button ghost"
                    onClick={() => setStatus.mutate({ itemId: item.item_id, status: 'known' })}
                  >
                    早认识了
                  </button>
                  <button
                    className="icon-button danger"
                    title="撤销自动收录"
                    aria-label={`撤销收录 ${item.word}`}
                    onClick={() => undoIngest.mutate(item.item_id)}
                  >
                    <Undo2 size={15} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {dueWords.length > 0 && (
        <section className="vocabulary-section">
          <h2>到期复习 <StatusBadge tone="warning">{dueWords.length}</StatusBadge></h2>
          <div className="vocabulary-grid">
            {dueWords.map((item) => (
              <article className="vocabulary-card due" key={item.item_id}>
                <div className="vocabulary-card-head">
                  <strong>{item.word}</strong>
                  <span>{item.meaning ?? ''}</span>
                </div>
                {item.example && <p>{item.example}</p>}
                <div className="vocabulary-card-actions">
                  <button className="button secondary" onClick={() => schedule.mutate(item.item_id)}>
                    <CalendarClock size={15} />已复习，3 天后再来
                  </button>
                  <button className="icon-button danger" title="不再学习这个词" aria-label={`不再学习 ${item.word}`} onClick={() => setStatus.mutate({ itemId: item.item_id, status: 'dismissed' })}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="vocabulary-section">
        <h2>全部词汇</h2>
        {items.isPending && <LoadingState label="正在读取词表" />}
        {items.isError && <ErrorState error={items.error} />}
        {!items.isPending && !items.isError && (
          <div className="vocabulary-grid">
            {allWords.map((item) => (
              <article className="vocabulary-card" key={item.item_id}>
                <div className="vocabulary-card-head">
                  <strong>{item.word}</strong>
                  <span>{item.meaning ?? ''}</span>
                </div>
                {item.collocations.length > 0 && (
                  <p className="vocabulary-collocations">{item.collocations.join(' · ')}</p>
                )}
                <div className="vocabulary-card-foot">
                  <StatusBadge tone={item.status === 'learning' ? 'warning' : 'success'}>
                    {item.status === 'learning' ? '学习中' : '已掌握'}
                  </StatusBadge>
                  <small>{item.review_count} 次复习</small>
                  {item.status === 'learning' && (
                    <button className="button ghost" onClick={() => schedule.mutate(item.item_id)}>
                      <CalendarClock size={14} />安排复习
                    </button>
                  )}
                  {item.status === 'learning' && (
                    <button className="button ghost" onClick={() => setStatus.mutate({ itemId: item.item_id, status: 'dismissed' })}>
                      <CheckCircle2 size={14} />不再学习
                    </button>
                  )}
                </div>
              </article>
            ))}
            {allWords.length === 0 && (
              <p className="muted">还没有词汇。在对话里遇到生词时直接说“把这个词记下来”，或者用上面的表单添加。</p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
