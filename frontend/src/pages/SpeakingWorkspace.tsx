import { ArrowRight, CheckCircle2, ClipboardCopy, MessageSquareText, Mic2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '../components/Common'

type Stage = 'step1' | 'recording' | 'returned'

export function SpeakingWorkspace() {
  const [searchParams] = useSearchParams()
  const practiceUnitId = searchParams.get('practice_unit_id')
  const [stage, setStage] = useState<Stage>(() => {
    const saved = window.sessionStorage.getItem('yanxi-speaking-stage')
    return saved === 'recording' || saved === 'returned' ? (saved as Stage) : 'step1'
  })

  function goRecording() {
    window.sessionStorage.setItem('yanxi-speaking-stage', 'recording')
    setStage('recording')
  }

  function goReturned() {
    window.sessionStorage.setItem('yanxi-speaking-stage', 'returned')
    setStage('returned')
  }

  function copyTaskPrompt() {
    void navigator.clipboard?.writeText(
      '我现在去录一段口语练习。稍后我会把录音转写贴回来，请先不要点评，等我贴回内容后再从清晰度、自然度和语法三方面点评。'
    )
  }

  return (
    <div className="page page-narrow">
      <PageHeader
        eyebrow="Speaking"
        title="口语练习"
        description="两步完成：先在这里领任务，再去语音工具开口练；练完把转写贴回来点评。练的过程中不纠正自己，回来再对。"
      />
      {practiceUnitId && <p className="muted">来自今日计划的练习：<code>{practiceUnitId}</code></p>}

      {stage === 'step1' && (
        <>
          <section className="settings-panel">
            <div className="section-heading">
              <div><h2>第一步 · 领取任务</h2><p>在对话里对老师说“给我一个口语练习场景”，老师会给出场景、角色、追问和练习重点。</p></div>
              <Mic2 size={20} />
            </div>
            <div className="speaking-step-guide">
              <ol>
                <li>在对话里领取一个场景任务</li>
                <li>把任务里的提示词复制到你的语音工具</li>
                <li>按提示词开口练习，不用管对错</li>
              </ol>
            </div>
            <div className="settings-support-actions">
              <Link className="button primary" to="/today"><MessageSquareText size={16} />去对话里领取任务 <ArrowRight size={14} /></Link>
              <button className="button secondary" onClick={goRecording}><Mic2 size={16} />我已经拿到任务了，去录音</button>
            </div>
          </section>

          <section className="settings-panel speaking-preview">
            <div className="section-heading">
              <div><h2>练完之后</h2><p>回到这个页面点“我录完了”，再回对话贴回转写；老师从清晰度、自然度和语法三方面点评。</p></div>
              <Sparkles size={20} />
            </div>
          </section>
        </>
      )}

      {stage === 'recording' && (
        <>
          <section className="settings-panel speaking-recording-card">
            <div className="section-heading">
              <div><h2>第二步 · 录音去了</h2><p>去用你顺手的语音工具开口练。练完把录音转成文字（或直接录音文件），带回来贴给老师。</p></div>
              <Mic2 size={20} />
            </div>
            <div className="speaking-step-guide">
              <ol>
                <li>打开语音工具，按任务提示词开口练</li>
                <li>练完把录音转写出来（或保存录音文件）</li>
                <li>回到这里点“我录完了”，再去对话贴回内容</li>
              </ol>
            </div>
            <div className="settings-support-actions">
              <button className="button secondary" onClick={copyTaskPrompt}>
                <ClipboardCopy size={16} />复制一句“我要去录音”的说明
              </button>
              <button className="button primary" onClick={goReturned}><CheckCircle2 size={16} />我录完了，要贴回转写</button>
            </div>
          </section>
        </>
      )}

      {stage === 'returned' && (
        <>
          <section className="settings-panel speaking-returned-card">
            <div className="section-heading">
              <div><h2>带回来点评</h2><p>把你说的话（文字或录音文件）粘回对话。老师会先看内容，再从清晰度、自然度和语法三方面点评，并告诉你下一步练什么。</p></div>
              <Sparkles size={20} />
            </div>
            <div className="settings-support-actions">
              <Link className="button primary" to="/today"><MessageSquareText size={16} />去对话贴回转写 <ArrowRight size={14} /></Link>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
