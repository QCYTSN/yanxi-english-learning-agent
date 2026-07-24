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
        model_display_name: adapterId === 'manual' ? modelName || null : null,
        agent_session_id: adapterId === 'manual' ? agentSessionId || null : null,
      }),
    }),
    onSuccess: (run) => {
      setActiveRun(run)
      if (run.status === 'persisted') onPersisted()
    },
  })
  useEffect(() => {
    if (!activeRunId || !activeRunStatus || ['persisted', 'test_passed', 'failed', 'cancelled', 'invalid_output', 'awaiting_import'].includes(activeRunStatus)) return
    const source = new EventSource(`/api/v1/agent-runs/${activeRunId}/events`)
    const refresh = () => void api<AgentRun>(`/api/v1/agent-runs/${activeRunId}`).then((run) => {
      setActiveRun(run)
      if (run.status === 'persisted') {
        source.close()
        onPersisted()
      } else if (run.status === 'test_passed') {
        source.close()
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
      <div>
        <p className="eyebrow">Feedback</p>
        <h2 id="feedback-heading">获取结构化反馈</h2>
        <p>Claude Code 和 OpenCode 才会调用真实 Agent；Manual 用于当前桌面对话或其他 Agent。</p>
      </div>
      <div className="agent-actions">
        <div className="mock-test-callout">
          <strong>工程管线自检</strong>
          <span>只检查 UI → Runtime → Schema，不连接 Agent、不评分、不写入学习记录。</span>
          <button className="button ghost" disabled={create.isPending} onClick={() => create.mutate('mock')}><Bot size={18} />运行管线自检</button>
        </div>
        <label className="consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />我确认可以将本次个人内容交给所选 Agent，一次有效</label>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('claude')}><Bot size={18} />调用 Claude Code CLI（推荐）</button>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('opencode')}><Bot size={18} />调用 OpenCode CLI（实验性）</button>
        <div className="manual-identity-fields"><label>Manual Agent / Provider<input value={agentProvider} onChange={(event) => setAgentProvider(event.target.value)} placeholder="例如 Codex Desktop；不确定可留空" /></label><label>Manual 模型<input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="以 Agent 实际显示为准；未知可留空" /></label><label>外部会话 ID（可选）<input value={agentSessionId} onChange={(event) => setAgentSessionId(event.target.value)} /></label></div>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('manual')}><FileInput size={18} />生成 Manual 任务包</button>
      </div>
      {create.isError && <ErrorState error={create.error} />}
      {activeRun && (
        <div className="agent-run-status">
          <StatusBadge tone={activeRun.status === 'failed' || activeRun.status === 'invalid_output' ? 'neutral' : activeRun.status === 'persisted' || activeRun.status === 'test_passed' ? 'success' : 'warning'}>
            {runStatusLabel(activeRun.status)}
          </StatusBadge>
          <span>Adapter：{activeRun.adapter_id}</span>
          {activeRun.adapter_id !== 'mock' && <span>模型：{activeRun.model_display_name ?? activeRun.model_id ?? '等待 Agent 回报'}</span>}
          <span>第 {activeRun.attempt_count ?? 1} 次执行</span>
          {['queued', 'running'].includes(activeRun.status) && <span>最长等待：{activeRun.timeout_seconds} 秒</span>}
          {activeRun.status === 'test_passed' && <strong>管线正常；未调用任何模型，也没有生成雅思分数。</strong>}
          {activeRun.result?.error && <span className="agent-error-detail">{activeRun.result.error.message}</span>}
          {activeRun.recovery_action && <span>恢复建议：{recoveryActionLabel(activeRun.recovery_action)}</span>}
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

function runStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: '已排队',
    running: '正在调用 Agent',
    validating: '正在验证结果',
    persisting: '正在保存正式反馈',
    persisted: '真实反馈已保存',
    test_passed: '管线自检通过',
    awaiting_import: '等待 Manual 结果',
    failed: '调用失败',
    cancelled: '已取消',
    invalid_output: '结果格式无效',
  }
  return labels[status] ?? status
}

function recoveryActionLabel(action: string) {
  const labels: Record<string, string> = {
    check_claude_provider_then_retry: '请检查 CCSwitch、中转 API 和系统代理，确认 Claude Code 最小请求能返回后再重试。',
    reauthenticate_claude_then_retry: '请检查 Claude Code 当前使用的认证方式或中转 Provider，再重试。',
    check_agent_cli_then_retry: '请先确认所选 Agent CLI 能在终端独立返回，再重试。',
    retry_with_longer_timeout: '请先检查 Agent CLI 的登录和连接状态，再重试。',
    refresh_session_and_retry: '学习记录版本已变化，请刷新页面后重试。',
    correct_and_import: '请修正结构化结果后重新导入。',
    retry: '请检查 Agent 状态后重试。',
  }
  return labels[action] ?? action
}
