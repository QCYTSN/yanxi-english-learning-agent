import type { Bootstrap } from '../api/client'
import { PageHeader, StatusBadge } from '../components/Common'

export function SettingsPage({ bootstrap }: { bootstrap: Bootstrap }) {
  return (
    <div className="page page-narrow">
      <PageHeader eyebrow="Settings" title="本地运行状态" description="V0.7 不提供模型选择；这里只说明当前连接和能力边界。" />
      <section className="settings-section">
        <h2>核心服务</h2>
        <dl className="definition-list"><div><dt>Core 版本</dt><dd>{bootstrap.core_version}</dd></div><div><dt>数据库</dt><dd><StatusBadge tone={bootstrap.health.database ? 'success' : 'warning'}>{bootstrap.health.database ? '可用' : '不可用'}</StatusBadge></dd></div><div><dt>数据范围</dt><dd>IELTS Academic · 本地优先</dd></div></dl>
      </section>
      <section className="settings-section">
        <h2>Agent 方式</h2>
        <div className="adapter-list">{bootstrap.agents.map((agent) => <article key={agent.id}><div><h3>{agent.label}</h3><p>{agent.id === 'manual' ? '导出任务包并导入结构化结果，适用于任意 Agent。' : '用于验证反馈、取消、冲突和保存流程。'}</p></div><StatusBadge tone="success">可用</StatusBadge></article>)}</div>
      </section>
      <section className="settings-section"><h2>隐私边界</h2><p>Manual Adapter 会在导出包含个人作文或私有材料的任务包前要求一次性确认。确认不持久化。</p></section>
    </div>
  )
}
