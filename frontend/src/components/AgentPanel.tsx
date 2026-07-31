import { useMutation, useQuery } from '@tanstack/react-query'
import { Bot, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  idempotencyKey,
  jsonBody,
  type AgentRun,
  type ModelProvider,
} from '../api/client'
import { ErrorState, StatusBadge } from './Common'

export function AgentPanel({ sessionId, contract, action, onPersisted }: {
  sessionId: string
  contract: 'writing-review@1' | 'writing-mock-review@1' | 'reading-review@1' | 'listening-review@1' | 'speaking-evaluation@1'
  action: string
  onPersisted: () => void
}) {
  const [consent, setConsent] = useState(false)
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null)
  const activeRunId = activeRun?.run_id
  const activeRunStatus = activeRun?.status
  const providers = useQuery({
    queryKey: ['model-providers'],
    queryFn: () => api<ModelProvider[]>('/api/v1/model-providers'),
  })
  const primary = providers.data?.find((provider) => provider.role === 'primary' && provider.is_enabled)
  const create = useMutation({
    mutationFn: ({ pipelineTest = false }: { pipelineTest?: boolean }) => api<AgentRun>('/api/v1/agent-runs', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: jsonBody({
        adapter_id: pipelineTest ? 'mock' : null,
        model_provider_id: pipelineTest ? null : primary?.provider_id ?? null,
        study_session_id: sessionId,
        action,
        output_contract: contract,
        explicit_consent: pipelineTest ? false : consent,
      }),
    }),
    onSuccess: (run) => {
      setActiveRun(run)
      if (run.status === 'persisted') onPersisted()
    },
  })

  useEffect(() => {
    if (!activeRunId || !activeRunStatus || ['persisted', 'test_passed', 'failed', 'cancelled', 'invalid_output'].includes(activeRunStatus)) return
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
    source.addEventListener('progress', refresh)
    source.addEventListener('completed', refresh)
    source.addEventListener('failed', refresh)
    source.addEventListener('cancelled', refresh)
    source.onerror = refresh
    return () => source.close()
  }, [activeRunId, activeRunStatus, onPersisted])

  return (
    <section className="agent-panel" aria-labelledby="feedback-heading">
      <div className="agent-panel-heading">
        <div>
          <p className="eyebrow">Evidence feedback</p>
          <h2 id="feedback-heading">获取结构化反馈</h2>
          <p>教学 Runtime 会注入对应 Skill、必要证据和输出 Schema；模型无法直接修改学习记录。</p>
        </div>
        <ShieldCheck size={21} aria-hidden="true" />
      </div>
      <div className="agent-actions">
        {primary ? (
          <>
            <div className="selected-provider-summary">
              <span>主模型</span>
              <strong>{primary.display_name}</strong>
              <small>{primary.model_id ?? '使用服务默认模型'}{providers.data?.some((item) => item.role === 'fallback') ? ' · 已配置备用模型' : ''}</small>
            </div>
            <label className="consent">
              <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              我确认可以把本次必要内容交给主模型处理；本次有效
            </label>
            <button className="button primary" disabled={!consent || create.isPending || !primary.available} onClick={() => create.mutate({})}>
              <Bot size={18} />获取智能反馈
            </button>
          </>
        ) : (
          <div className="empty-model-callout">
            <p>尚未连接主模型。练习和保存不受影响，但智能反馈需要先完成连接。</p>
            <Link className="button secondary" to="/settings/models">连接模型</Link>
          </div>
        )}
        <details className="pipeline-test-details">
          <summary>开发者：验证反馈管线</summary>
          <p>只检查 UI → Runtime → Schema，不连接模型、不评分、不写学习记录。</p>
          <button className="button ghost" disabled={create.isPending} onClick={() => create.mutate({ pipelineTest: true })}>
            运行本地管线自检
          </button>
        </details>
      </div>
      {(create.error || providers.error) && <ErrorState error={create.error ?? providers.error} />}
      {activeRun && (
        <div className="agent-run-status">
          <StatusBadge tone={activeRun.status === 'failed' || activeRun.status === 'invalid_output' ? 'neutral' : activeRun.status === 'persisted' || activeRun.status === 'test_passed' ? 'success' : 'warning'}>
            {runStatusLabel(activeRun.status)}
          </StatusBadge>
          {activeRun.model_provider_id && <span>模型服务：{activeRun.model_provider_id}</span>}
          {activeRun.adapter_id !== 'mock' && <span>模型：{activeRun.model_display_name ?? activeRun.model_id ?? '正在确认'}</span>}
          <span>第 {activeRun.attempt_count ?? 1} 次执行</span>
          {activeRun.status === 'test_passed' && <strong>管线正常；未调用模型，也没有生成分数。</strong>}
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
    </section>
  )
}

function runStatusLabel(status: string) {
  const labels: Record<string, string> = {
    queued: '已排队',
    running: '正在生成反馈',
    validating: '正在验证结果',
    persisting: '正在保存正式反馈',
    persisted: '反馈已保存',
    test_passed: '管线自检通过',
    failed: '模型调用失败',
    cancelled: '已取消',
    invalid_output: '结果格式无效',
  }
  return labels[status] ?? status
}

function recoveryActionLabel(action: string) {
  const labels: Record<string, string> = {
    configure_primary_model: '请先在设置中选择一个主模型。',
    configure_model_credential: '请补充模型服务的登录或 API Key。',
    check_model_credential: '模型服务拒绝了凭据，请重新登录或更新 API Key。',
    check_model_connection: '无法连接模型服务，请检查 Base URL、网络和本地服务状态。',
    check_model_route_then_retry: '主模型和备用模型均失败，请检查模型路线后重试。',
    check_primary_model_then_retry: '请检查主模型连接，再重试。',
    refresh_session_and_retry: '学习记录版本已变化，请刷新页面后重试。',
    connect_codex_then_retry: '请在设置中完成 ChatGPT 登录。',
    restart_codex_runtime_then_retry: 'OpenAI 登录组件已停止，请在设置中检查状态。',
    retry: '请检查模型连接后重试。',
  }
  return labels[action] ?? action
}
