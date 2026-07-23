import { useMutation } from '@tanstack/react-query'
import { Bot, ClipboardCopy, FileInput } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, idempotencyKey, jsonBody, type AgentRun } from '../api/client'
import { ErrorState, StatusBadge } from './Common'

export function AgentPanel({ sessionId, contract, action, onPersisted }: {
  sessionId: string
  contract: 'writing-review@1' | 'reading-review@1' | 'listening-review@1' | 'speaking-evaluation@1'
  action: string
  onPersisted: () => void
}) {
  const [consent, setConsent] = useState(false)
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null)
  const [manualResult, setManualResult] = useState('')
  const [agentProvider, setAgentProvider] = useState('')
  const [modelName, setModelName] = useState('')
  const [agentSessionId, setAgentSessionId] = useState('')
  const activeRunId = activeRun?.run_id
  const activeRunStatus = activeRun?.status
  const create = useMutation({
    mutationFn: (adapterId: 'mock' | 'manual' | 'opencode' | 'claude') => api<AgentRun>('/api/v1/agent-runs', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({
        adapter_id: adapterId,
        study_session_id: sessionId,
        action,
        output_contract: contract,
        explicit_consent: adapterId !== 'mock' ? consent : false,
        agent_provider: adapterId === 'manual' ? agentProvider || null : null,
        model_display_name: adapterId !== 'mock' ? modelName || null : null,
        agent_session_id: adapterId === 'manual' ? agentSessionId || null : null,
      }),
    }),
    onSuccess: (run) => {
      if (run.status === 'persisted') onPersisted()
      else setActiveRun(run)
    },
  })
  useEffect(() => {
    if (!activeRunId || !activeRunStatus || ['persisted', 'failed', 'cancelled', 'invalid_output', 'awaiting_import'].includes(activeRunStatus)) return
    const source = new EventSource(`/api/v1/agent-runs/${activeRunId}/events`)
    const refresh = () => void api<AgentRun>(`/api/v1/agent-runs/${activeRunId}`).then((run) => {
      setActiveRun(run)
      if (run.status === 'persisted') {
        source.close()
        onPersisted()
      }
    })
    source.addEventListener('status', refresh)
    source.addEventListener('completed', refresh)
    source.addEventListener('failed', refresh)
    source.addEventListener('cancelled', refresh)
    source.onerror = refresh
    return () => source.close()
  }, [activeRunId, activeRunStatus, onPersisted])
  const importResult = useMutation({
    mutationFn: () => {
      if (!activeRun) throw new Error('请先生成 Manual 任务包。')
      let result: unknown
      try { result = JSON.parse(manualResult) } catch { throw new Error('结构化结果不是有效 JSON。') }
      return api<AgentRun>(`/api/v1/agent-runs/${activeRun.run_id}/import`, { method: 'POST', body: jsonBody({
        result,
        agent_provider: agentProvider || null,
        model_display_name: modelName || null,
        agent_session_id: agentSessionId || null,
      }) })
    },
    onSuccess: () => onPersisted(),
  })
  const request: Record<string, unknown> | null = activeRun?.result?.request ?? null
  return (
    <section className="agent-panel" aria-labelledby="feedback-heading">
      <div><p className="eyebrow">Feedback</p><h2 id="feedback-heading">获取结构化反馈</h2><p>Mock 用于验证流程；Manual 可以把任务交给当前任意 Agent。</p></div>
      <div className="agent-actions">
        <button className="button secondary" disabled={create.isPending} onClick={() => create.mutate('mock')}><Bot size={18} />生成 Mock 反馈</button>
        <label className="consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />我确认可以将本次个人内容交给所选 Agent，一次有效</label>
        <div className="manual-identity-fields"><label>Agent / Provider<input value={agentProvider} onChange={(event) => setAgentProvider(event.target.value)} placeholder="例如 Claude Code；不确定可留空" /></label><label>模型<input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="以 Agent 实际显示为准；未知可留空" /></label><label>外部会话 ID（可选）<input value={agentSessionId} onChange={(event) => setAgentSessionId(event.target.value)} /></label></div>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('manual')}><FileInput size={18} />生成 Manual 任务包</button>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('opencode')}><Bot size={18} />调用 OpenCode CLI</button>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('claude')}><Bot size={18} />调用 Claude Code CLI</button>
      </div>
      {create.isError && <ErrorState error={create.error} />}
      {activeRun && (
        <div className="agent-run-status">
          <StatusBadge tone={activeRun.status === 'failed' || activeRun.status === 'invalid_output' ? 'neutral' : activeRun.status === 'persisted' ? 'success' : 'warning'}>
            {activeRun.status}
          </StatusBadge>
          <span>第 {activeRun.attempt_count ?? 1} 次执行</span>
          {activeRun.recovery_action && <span>恢复建议：{activeRun.recovery_action}</span>}
          {['queued', 'running', 'validating', 'persisting'].includes(activeRun.status) && (
            <button className="button ghost" onClick={() => void api<AgentRun>(`/api/v1/agent-runs/${activeRun.run_id}/cancel`, { method: 'POST' }).then(setActiveRun)}>取消</button>
          )}
          {['failed', 'cancelled', 'invalid_output'].includes(activeRun.status) && (
            <button className="button ghost" onClick={() => void api<AgentRun>(`/api/v1/agent-runs/${activeRun.run_id}/retry`, { method: 'POST' }).then(setActiveRun)}>重试</button>
          )}
        </div>
      )}
      {request && (
        <div className="manual-handoff">
          <div className="manual-heading"><h3>复制任务包</h3><StatusBadge tone="warning">等待导入</StatusBadge></div>
          <pre>{JSON.stringify(request, null, 2)}</pre>
          <button className="button secondary" onClick={() => void navigator.clipboard.writeText(JSON.stringify(request, null, 2))}><ClipboardCopy size={17} />复制</button>
          <label>粘贴 Agent 返回的结构化 JSON<textarea value={manualResult} onChange={(event) => setManualResult(event.target.value)} rows={10} placeholder="{ ... }" /></label>
          <button className="button primary" disabled={!manualResult || importResult.isPending} onClick={() => importResult.mutate()}>验证并保存反馈</button>
          {importResult.isError && <ErrorState error={importResult.error} />}
        </div>
      )}
    </section>
  )
}
