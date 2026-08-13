import { useQuery } from '@tanstack/react-query'
import { Headphones, RotateCcw, Volume2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type VocabularyItem } from '../api/client'
import { ErrorState, LoadingState, PageHeader } from '../components/Common'

type SeedResponse = {
  meta: { title: string; level_note: string }
  words: Array<{ word: string; yanxi_level: string }>
}

type ListenWord = {
  word: string
  meaning: string | null
  origin: 'my_words' | 'starter'
}

const SESSION_SIZE = 10

export function ListenPracticePage() {
  const myWords = useQuery({
    queryKey: ['vocabulary', 'all'],
    queryFn: () => api<VocabularyItem[]>('/api/v1/vocabulary?limit=500'),
  })
  const seed = useQuery({
    queryKey: ['vocabulary', 'seed'],
    queryFn: () => api<SeedResponse>('/api/v1/vocabulary/seed?limit=3000'),
  })

  const pool = useMemo<ListenWord[]>(() => {
    const mine = (myWords.data ?? [])
      .filter((item) => item.status === 'learning' && item.word.trim().length > 0)
      .map((item) => ({ word: item.word.trim(), meaning: item.meaning, origin: 'my_words' as const }))
    const owned = new Set(mine.map((item) => item.word.toLowerCase()))
    const starter = (seed.data?.words ?? [])
      .filter((item) => !owned.has(item.word.toLowerCase()))
      .map((item) => ({ word: item.word, meaning: null, origin: 'starter' as const }))
    return [...mine, ...starter]
  }, [myWords.data, seed.data])

  const [session, setSession] = useState<ListenWord[]>([])
  const [sessionIndex, setSessionIndex] = useState(0)
  const [answer, setAnswer] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [plays, setPlays] = useState(0)
  const speechSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

  const current = session[sessionIndex]

  function startSession() {
    if (pool.length === 0) return
    const shuffled = [...pool].sort(() => Math.random() - 0.5).slice(0, SESSION_SIZE)
    setSession(shuffled)
    setSessionIndex(0)
    setAnswer('')
    setRevealed(false)
    setPlays(0)
  }

  function play() {
    if (!current || !speechSupported) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(current.word)
    utterance.lang = 'en-GB'
    utterance.rate = 0.82
    window.speechSynthesis.speak(utterance)
    setPlays((count) => count + 1)
  }

  function check() {
    if (!current) return
    setRevealed(true)
  }

  function next() {
    setAnswer('')
    setRevealed(false)
    setPlays(0)
    if (sessionIndex + 1 < session.length) {
      setSessionIndex((index) => index + 1)
    } else {
      setSession([])
    }
  }

  const isLoading = myWords.isPending || seed.isPending
  const hasError = myWords.isError || seed.isError

  return (
    <div className="page page-typing">
      <PageHeader
        eyebrow="听言练习"
        title="先听，再写出来"
        description="系统语音读词，你拼写出来。听言和口语两步式不同：这里是先听再说——拼出来之前，先让耳朵认识它。"
      />
      {isLoading && <LoadingState label="正在准备词表" />}
      {hasError && <ErrorState error={myWords.error ?? seed.error} />}
      {!isLoading && !hasError && pool.length === 0 && (
        <div className="typing-empty">
          <Headphones size={28} strokeWidth={1.6} />
          <h2>还没有可听的词</h2>
          <p>在对话里让言蹊讲一个词，它会自动收进候选；也可以先到起步词表练习。</p>
          <Link className="button primary" to="/today">去对话里学词</Link>
        </div>
      )}
      {!isLoading && !hasError && pool.length > 0 && (
        <>
          <section className="typing-stats" aria-label="词表来源">
            <span>我的词 {(myWords.data ?? []).filter((item) => item.status === 'learning').length}</span>
            <span>本组 {session.length || SESSION_SIZE} 词</span>
            {plays > 0 && <span>已播放 {plays} 次</span>}
          </section>

          {session.length === 0 && !revealed ? (
            <div className="typing-start">
              <div className="typing-start-card">
                <h2>一组 {SESSION_SIZE} 个词</h2>
                <p>听言会读词给你听，你把它拼出来。可以反复播放，直到耳朵确认。拼对一枚朱印，拼错就看释义。</p>
                <button className="button primary" onClick={startSession}>
                  <Headphones size={16} /> 开始听言
                </button>
                {!speechSupported && <p className="muted">当前浏览器不支持系统语音，请用 Edge 或 Chrome 打开。</p>}
              </div>
            </div>
          ) : (
            current && (
              <section className="typing-stage">
                <div className="typing-progress" aria-label="本组进度">
                  {session.map((item, index) => (
                    <span
                      key={`${item.word}-${index}`}
                      className={`typing-seal${index < sessionIndex ? ' lit' : ''}${index === sessionIndex && revealed ? ' lit' : ''}`}
                      title={item.word}
                    />
                  ))}
                </div>

                <div className="typing-word">
                  {revealed ? (
                    <>
                      <h2 className="typing-word-done">{current.word}</h2>
                      {current.meaning && <p className="typing-meaning">{current.meaning}</p>}
                      <div className="typing-word-origin">
                        {current.origin === 'my_words' ? '来自我的词表' : '来自起步词表'}
                      </div>
                      <button className="button secondary" onClick={play} disabled={!speechSupported}>
                        <Volume2 size={15} /> 再听一次
                      </button>
                      <button className="button primary" onClick={next}>
                        {sessionIndex + 1 < session.length ? '下一个词' : '完成本组'} <RotateCcw size={15} />
                      </button>
                    </>
                  ) : (
                    <>
                      <h2 className="typing-word-hint">点播放，然后写下你听到的词</h2>
                      <div className="typing-target">🎧 ……</div>
                      <button className="listen-button" onClick={play} disabled={!speechSupported}>
                        <Volume2 size={24} /><span>{speechSupported ? '播放英式系统语音' : '不支持系统语音'}</span>
                      </button>
                      <input
                        className="typing-input"
                        value={answer}
                        onChange={(event) => setAnswer(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' && answer.trim()) check()
                        }}
                        placeholder="写下你听到的词…"
                        autoFocus
                        autoComplete="off"
                        autoCapitalize="off"
                        spellCheck={false}
                        aria-label="写下听到的词"
                      />
                      <button className="button primary" onClick={check} disabled={!answer.trim()}>
                        拼好了，看答案
                      </button>
                    </>
                  )}
                </div>
              </section>
            )
          )}
        </>
      )}
    </div>
  )
}
