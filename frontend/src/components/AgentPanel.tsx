import { useMutation } from '@tanstack/react-query'
import { Bot, ClipboardCopy, FileInput } from 'lucide-react'
import { useState } from 'react'
import { api, jsonBody } from '../api/client'
import { ErrorState, StatusBadge } from './Common'

type AgentRun = {
  run_id: string
  adapter_id: string
  status: string
  result?: { request?: Record<string, unknown> } | null
}

export function AgentPanel({ sessionId, contract, action, onPersisted }: {
  sessionId: string
  contract: 'writing-review@1' | 'reading-review@1'
  action: string
  onPersisted: () => void
}) {
  const [consent, setConsent] = useState(false)
  const [manualRun, setManualRun] = useState<AgentRun | null>(null)
  const [manualResult, setManualResult] = useState('')
  const create = useMutation({
    mutationFn: (adapterId: 'mock' | 'manual') => api<AgentRun>('/api/v1/agent-runs', {
      method: 'POST',
      body: jsonBody({
        adapter_id: adapterId,
        study_session_id: sessionId,
        action,
        output_contract: contract,
        explicit_consent: adapterId === 'manual' ? consent : false,
      }),
    }),
    onSuccess: (run) => {
      if (run.status === 'persisted') onPersisted()
      else setManualRun(run)
    },
  })
  const importResult = useMutation({
    mutationFn: () => {
      if (!manualRun) throw new Error('请先生成 Manual 任务包。')
      let result: unknown
      try { result = JSON.parse(manualResult) } catch { throw new Error('结构化结果不是有效 JSON。') }
      return api<AgentRun>(`/api/v1/agent-runs/${manualRun.run_id}/import`, { method: 'POST', body: jsonBody({ result }) })
    },
    onSuccess: () => onPersisted(),
  })
  const request: Record<string, unknown> | null = manualRun?.result?.request ?? null
  return (
    <section className="agent-panel" aria-labelledby="feedback-heading">
      <div><p className="eyebrow">Feedback</p><h2 id="feedback-heading">获取结构化反馈</h2><p>Mock 用于验证流程；Manual 可以把任务交给当前任意 Agent。</p></div>
      <div className="agent-actions">
        <button className="button secondary" disabled={create.isPending} onClick={() => create.mutate('mock')}><Bot size={18} />生成 Mock 反馈</button>
        <label className="consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />我确认可以将本次个人内容交给所选 Agent，一次有效</label>
        <button className="button secondary" disabled={!consent || create.isPending} onClick={() => create.mutate('manual')}><FileInput size={18} />生成 Manual 任务包</button>
      </div>
      {create.isError && <ErrorState error={create.error} />}
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
