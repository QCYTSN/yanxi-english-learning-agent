import { ArrowRight, MessageSquareText, Mic2, Sparkles } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { PageHeader } from '../components/Common'

export function SpeakingWorkspace() {
  const [searchParams] = useSearchParams()
  const practiceUnitId = searchParams.get('practice_unit_id')

  return (
    <div className="page page-narrow">
      <PageHeader
        eyebrow="Speaking"
        title="口语练习"
        description="练习分两步：先在这里拿到练习任务，再用你顺手的语音工具开口练，练完把内容带回来让老师点评。"
      />
      {practiceUnitId && <p className="muted">来自今日计划的练习：<code>{practiceUnitId}</code></p>}

      <section className="settings-panel">
        <div className="section-heading">
          <div><h2>第一步 · 领取练习任务</h2><p>在对话里对老师说“给我一个口语练习场景”，老师会给出场景、角色和追问，并说明练习重点。</p></div>
          <Mic2 size={20} />
        </div>
        <div className="settings-support-actions">
          <Link className="button primary" to="/today"><MessageSquareText size={16} />去对话里领取任务 <ArrowRight size={14} /></Link>
        </div>
      </section>

      <section className="settings-panel">
        <div className="section-heading">
          <div><h2>第二步 · 开口练习</h2><p>用你喜欢的语音工具（手机语音助手、AI 语音应用等）按任务开口说；练习时不用纠正自己，流畅表达就好。</p></div>
          <Sparkles size={20} />
        </div>
      </section>

      <section className="settings-panel">
        <div className="section-heading">
          <div><h2>第三步 · 带回来点评</h2><p>把你说的话（文字或录音）粘回对话，老师会从清晰度、自然度和语法三个方面点评，并告诉你下一步练什么。</p></div>
          <ArrowRight size={20} />
        </div>
        <div className="settings-support-actions">
          <Link className="button secondary" to="/today">回到对话 <ArrowRight size={14} /></Link>
        </div>
      </section>
    </div>
  )
}
