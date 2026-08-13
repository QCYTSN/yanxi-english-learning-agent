import { useMutation, useQuery } from '@tanstack/react-query'
import { Keyboard, RotateCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, jsonBody, type VocabularyItem } from '../api/client'
import { ErrorState, LoadingState, PageHeader } from '../components/Common'

type SeedResponse = {
  meta: {
    seed_id: string
    title: string
    level_note: string
    bands: Record<string, string>
    source: { origin: string; rights: string; note: string }
  }
  words: Array<{ word: string; yanxi_level: string }>
}

type TypingWord = {
  word: string
  origin: 'my_words' | 'starter'
  meaning?: string | null
}

const SESSION_SIZE = 10

export function TypingPracticePage() {
  const myWords = useQuery({
    queryKey: ['vocabulary', 'all'],
    queryFn: () => api<VocabularyItem[]>('/api/v1/vocabulary?limit=500'),
  })
  const seed = useQuery({
    queryKey: ['vocabulary', 'seed'],
    queryFn: () => api<SeedResponse>('/api/v1/vocabulary/seed?limit=100'),
  })

  const pool = useMemo<TypingWord[]>(() => {
    const mine = (myWords.data ?? [])
      .filter((item) => item.status === 'learning' && item.word.trim().length > 0)
      .map((item) => ({ word: item.word.trim(), origin: 'my_words' as const, meaning: item.meaning }))
    const owned = new Set(mine.map((item) => item.word.toLowerCase()))
    const starter = (seed.data?.words ?? [])
      .filter((item) => !owned.has(item.word.toLowerCase()))
      .map((item) => ({ word: item.word, origin: 'starter' as const, meaning: null }))
    return [...mine, ...starter]
  }, [myWords.data, seed.data])

  const [session, setSession] = useState<TypingWord[]>([])
  const [sessionIndex, setSessionIndex] = useState(0)
  const [input, setInput] = useState('')
  const [mistakes, setMistakes] = useState(0)
  const [done, setDone] = useState(false)
  const reportMistake = useMutation({
    mutationFn: (word: string) => api('/api/v1/vocabulary/typing-mistake', {
      method: 'POST',
      body: jsonBody({ word }),
    }),
  })

  function startSession() {
    if (pool.length === 0) return
    const shuffled = [...pool].sort(() => Math.random() - 0.5).slice(0, SESSION_SIZE)
    setSession(shuffled)
    setSessionIndex(0)
    setInput('')
    setMistakes(0)
    setDone(false)
  }

  const current = session[sessionIndex]
  const finishedWord = done && current != null

  function handleChange(value: string) {
    if (finishedWord || !current) return
    setInput(value)
    const target = current.word
    if (value.length > target.length) {
      setMistakes((count) => count + 1)
      reportMistake.mutate(target)
      setInput('')
      return
    }
    const isTypo = !target.startsWith(value)
    if (isTypo) {
      setMistakes((count) => count + 1)
      reportMistake.mutate(target)
      setInput('')
    } else if (value === target) {
      setDone(true)
    }
  }

  function nextWord() {
    setDone(false)
    setInput('')
    if (sessionIndex + 1 < session.length) {
      setSessionIndex((index) => index + 1)
    } else {
      setSession([])
    }
  }

  const isLoading = myWords.isPending || seed.isPending
  const hasError = myWords.isError || seed.isError
  const totalWords = pool.length
  const myCount = (myWords.data ?? []).filter((item) => item.status === 'learning').length

  return (
    <div className="page page-typing">
      <PageHeader
        eyebrow="打字练习"
        title="把词打出来"
        description="先拼出来，再谈认识。打对的字亮起一枚朱红印章，打错只描一道墨痕——不用怕错，错了再来。"
      />
      {isLoading && <LoadingState label="正在准备词表" />}
      {hasError && <ErrorState error={myWords.error ?? seed.error} />}
      {!isLoading && !hasError && pool.length === 0 && (
        <div className="typing-empty">
          <Keyboard size={28} strokeWidth={1.6} />
          <h2>还没有可练的词</h2>
          <p>
            在对话里让言蹊讲一个词，它会自动收进候选；也可以在词表里手动添加。
          </p>
          <Link className="button primary" to="/today">去对话里学词</Link>
        </div>
      )}
      {!isLoading && !hasError && pool.length > 0 && (
        <>
          <section className="typing-stats" aria-label="词表来源">
            <span>我的词 {myCount}</span>
            <span>起步词表 {Math.max(0, totalWords - myCount)}</span>
            <span>本组 {session.length || SESSION_SIZE} 词</span>
            {mistakes > 0 && <span className="typing-mistakes">重来 {mistakes} 次</span>}
          </section>

          {session.length === 0 && !finishedWord ? (
            <div className="typing-start">
              <div className="typing-start-card">
                <h2>一组 {SESSION_SIZE} 个词</h2>
                <p>
                  我的词表优先，不够时用起步词表补齐。打对一个词，印章就亮一格；打错了墨迹会淡一笔，重来就好。
                </p>
                <button className="button primary" onClick={startSession}>
                  <Keyboard size={16} /> 开始打词
                </button>
              </div>
            </div>
          ) : (
            current && (
              <section className="typing-stage">
                <div className="typing-progress" aria-label="本组进度">
                  {session.map((item, index) => (
                    <span
                      key={`${item.word}-${index}`}
                      className={`typing-seal${index < sessionIndex ? ' lit' : ''}${index === sessionIndex && finishedWord ? ' lit' : ''}`}
                      title={item.word}
                    />
                  ))}
                </div>

                <div className="typing-word">
                  {finishedWord ? (
                    <>
                      <h2 className="typing-word-done">{current.word}</h2>
                      {current.meaning && <p className="typing-meaning">{current.meaning}</p>}
                      <div className="typing-word-origin">
                        {current.origin === 'my_words' ? '来自我的词表' : '来自起步词表'}
                      </div>
                      <button className="button primary" onClick={nextWord}>
                        {sessionIndex + 1 < session.length ? '下一个词' : '完成本组'} <RotateCcw size={15} />
                      </button>
                    </>
                  ) : (
                    <>
                      <h2 className="typing-word-hint">请看词，然后把它完整打出来</h2>
                      <div className="typing-target">{current.word}</div>
                      <input
                        className="typing-input"
                        value={input}
                        onChange={(event) => handleChange(event.target.value)}
                        placeholder="在这里打字…"
                        autoFocus
                        autoComplete="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        aria-label={`输入 ${current.word}`}
                      />
                    </>
                  )}
                </div>

                {finishedWord && sessionIndex + 1 >= session.length && (
                  <p className="muted">本组完成。打错的次数会记在心里，下次对话里主动提醒你。</p>
                )}
              </section>
            )
          )}
        </>
      )}
    </div>
  )
}
