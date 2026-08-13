import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  Check,
  CirclePause,
  History,
  Pencil,
  Plus,
  Target,
  Trash2,
  X,
} from 'lucide-react'
import { FormEvent, useState } from 'react'
import {
  api,
  jsonBody,
  type LearnerMemory,
  type LearnerMemoryConflict,
  type LearnerMemoryRevision,
  type LearningModelSnapshot,
  type LearningObjective,
} from '../api/client'
import { ErrorState, LoadingState, StatusBadge } from '../components/Common'
import {
  dimensionLabel,
  friendlyDate,
  LEARNING_DIMENSIONS,
  memorySourceLabel,
  memoryTypeLabel,
  objectiveStatusLabel,
  skillPresentation,
} from '../learningPresentation'

export function LearningMemorySection() {
  const queryClient = useQueryClient()
  const [goalTitle, setGoalTitle] = useState('')
  const [goalDimension, setGoalDimension] = useState<(typeof LEARNING_DIMENSIONS)[number]['id']>('reading')
  const [goalSkill, setGoalSkill] = useState('')
  const [goalDue, setGoalDue] = useState('')
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null)
  const [memoryDraft, setMemoryDraft] = useState('')

  const learningModel = useQuery({
    queryKey: ['learning-model'],
    queryFn: () => api<LearningModelSnapshot>('/api/v1/learning-model'),
  })
  const memories = useQuery({
    queryKey: ['learner-memories', 'active'],
    queryFn: () => api<LearnerMemory[]>('/api/v1/learner-memories?status=active&validity_status=current&limit=100'),
  })
  const conflicts = useQuery({
    queryKey: ['learner-memory-conflicts', 'open'],
    queryFn: () => api<LearnerMemoryConflict[]>('/api/v1/learner-memory-conflicts?status=open&limit=100'),
  })
  const createObjective = useMutation({
    mutationFn: () => api<LearningObjective>('/api/v1/learning-objectives', {
      method: 'POST',
      body: jsonBody({
        title: goalTitle,
        dimension_id: goalDimension,
        skill_id: goalSkill || null,
        due_at: goalDue || null,
        status: 'active',
        priority: 60,
      }),
    }),
    onSuccess: async () => {
      setGoalTitle('')
      setGoalSkill('')
      setGoalDue('')
      await queryClient.invalidateQueries({ queryKey: ['learning-model'] })
    },
  })
  const updateObjective = useMutation({
    mutationFn: ({ objective, status }: { objective: LearningObjective; status: LearningObjective['status'] }) => (
      api<LearningObjective>(`/api/v1/learning-objectives/${objective.objective_id}`, {
        method: 'PATCH',
        body: jsonBody({ status, expected_revision: objective.revision }),
      })
    ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['learning-model'] }),
  })
  const updateMemory = useMutation({
    mutationFn: ({ memory, statement }: { memory: LearnerMemory; statement: string }) => (
      api<LearnerMemory>(`/api/v1/learner-memories/${memory.memory_id}`, {
        method: 'PATCH',
        body: jsonBody({
          statement,
          expected_revision: memory.revision,
          change_reason: 'learner_edit',
        }),
      })
    ),
    onSuccess: async () => {
      setEditingMemoryId(null)
      setMemoryDraft('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['learner-memories'] }),
        queryClient.invalidateQueries({ queryKey: ['learner-memory-conflicts'] }),
      ])
    },
  })
  const deleteMemory = useMutation({
    mutationFn: (memoryId: string) => api(`/api/v1/learner-memories/${memoryId}`, { method: 'DELETE' }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['learner-memories'] }),
        queryClient.invalidateQueries({ queryKey: ['learner-memory-conflicts'] }),
      ])
    },
  })
  const resolveConflict = useMutation({
    mutationFn: ({ conflictId, resolution }: {
      conflictId: string
      resolution: 'keep_left' | 'keep_right' | 'keep_both' | 'dismiss_both'
    }) => api(`/api/v1/learner-memory-conflicts/${conflictId}/resolve`, {
      method: 'POST',
      body: jsonBody({ resolution }),
    }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['learner-memories'] }),
        queryClient.invalidateQueries({ queryKey: ['learner-memory-conflicts'] }),
      ])
    },
  })

  const activeObjectives = learningModel.data?.objectives.filter((item) => (
    ['active', 'planned', 'paused'].includes(item.status)
  )) ?? []
  const goalSkills = learningModel.data?.skills.filter((item) => item.dimension_id === goalDimension) ?? []
  const mutationError = createObjective.error
    ?? updateObjective.error
    ?? updateMemory.error
    ?? deleteMemory.error
    ?? resolveConflict.error

  function submitGoal(event: FormEvent) {
    event.preventDefault()
    if (goalTitle.trim()) createObjective.mutate()
  }

  function confirmForget(memory: LearnerMemory) {
    if (window.confirm(`确定让老师忘记“${memory.statement}”吗？此操作会删除这条本地记忆。`)) {
      deleteMemory.mutate(memory.memory_id)
    }
  }

  return (
    <div className="settings-detail-stack learning-memory-settings">
      <section className="settings-panel">
        <div className="section-heading">
          <div><h2>学习目标</h2><p>目标决定老师优先关注什么；考试分数目标仍在“学习档案”中管理。</p></div>
          <Target size={20} aria-hidden="true" />
        </div>
        <form className="learning-goal-form" onSubmit={submitGoal}>
          <label className="learning-goal-title">想重点改善什么
            <input
              value={goalTitle}
              onChange={(event) => setGoalTitle(event.target.value)}
              placeholder="例如：稳定判断 Reading 的 Not Given"
              maxLength={200}
            />
          </label>
          <label>科目
            <select value={goalDimension} onChange={(event) => {
              setGoalDimension(event.target.value as typeof goalDimension)
              setGoalSkill('')
            }}>
              {LEARNING_DIMENSIONS.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label>具体能力（可选）
            <select value={goalSkill} onChange={(event) => setGoalSkill(event.target.value)}>
              <option value="">由老师判断</option>
              {goalSkills.map((skill) => <option value={skill.skill_id} key={skill.skill_id}>{skillPresentation(skill).title}</option>)}
            </select>
          </label>
          <label>希望完成日期（可选）
            <input type="date" value={goalDue} onChange={(event) => setGoalDue(event.target.value)} />
          </label>
          <button className="button primary" disabled={!goalTitle.trim() || createObjective.isPending} type="submit">
            <Plus size={16} />添加目标
          </button>
        </form>
        {learningModel.isPending && <LoadingState label="正在读取学习目标" />}
        <div className="learning-goal-list">
          {activeObjectives.map((objective) => (
            <article key={objective.objective_id}>
              <span className="learning-goal-module">{dimensionLabel(objective.dimension_id)}</span>
              <div>
                <strong>{objective.title}</strong>
                <small>
                  {objectiveStatusLabel(objective.status)}
                  {objective.due_at ? ` · ${friendlyDate(objective.due_at)}前` : ''}
                </small>
              </div>
              <div className="learning-goal-actions">
                {objective.status === 'paused' ? (
                  <button type="button" disabled={updateObjective.isPending} onClick={() => updateObjective.mutate({ objective, status: 'active' })}>
                    <Check size={15} />继续
                  </button>
                ) : (
                  <>
                    <button type="button" disabled={updateObjective.isPending} onClick={() => updateObjective.mutate({ objective, status: 'achieved' })}>
                      <Check size={15} />已达成
                    </button>
                    <button type="button" disabled={updateObjective.isPending} onClick={() => updateObjective.mutate({ objective, status: 'paused' })}>
                      <CirclePause size={15} />暂停
                    </button>
                  </>
                )}
                <button type="button" disabled={updateObjective.isPending} onClick={() => updateObjective.mutate({ objective, status: 'archived' })} title="归档目标">
                  <Archive size={15} /><span className="sr-only">归档</span>
                </button>
              </div>
            </article>
          ))}
          {!learningModel.isPending && activeObjectives.length === 0 && (
            <p className="settings-empty-line">还没有单独设定学习目标。老师仍会根据正式练习证据安排下一步。</p>
          )}
        </div>
      </section>

      <section className="settings-panel">
        <div className="section-heading">
          <div><h2>老师记住的内容</h2><p>只保留对后续教学有帮助的偏好和观察；你可以随时修改或让老师忘记。</p></div>
          <StatusBadge tone="neutral">{memories.data?.length ?? 0} 条</StatusBadge>
        </div>

        {(conflicts.data?.length ?? 0) > 0 && (
          <div className="memory-conflict-list">
            <h3>有些信息需要你确认</h3>
            {conflicts.data?.map((conflict) => (
              <article key={conflict.conflict_id}>
                <p>老师发现下面两条信息可能不一致：</p>
                <div><span>上一条</span><strong>{conflict.left_memory?.statement ?? '内容已不存在'}</strong></div>
                <div><span>下一条</span><strong>{conflict.right_memory?.statement ?? '内容已不存在'}</strong></div>
                <footer>
                  <button type="button" disabled={resolveConflict.isPending} onClick={() => resolveConflict.mutate({ conflictId: conflict.conflict_id, resolution: 'keep_left' })}>采用上一条</button>
                  <button type="button" disabled={resolveConflict.isPending} onClick={() => resolveConflict.mutate({ conflictId: conflict.conflict_id, resolution: 'keep_right' })}>采用下一条</button>
                  <button type="button" disabled={resolveConflict.isPending} onClick={() => resolveConflict.mutate({ conflictId: conflict.conflict_id, resolution: 'keep_both' })}>都保留</button>
                  <button type="button" disabled={resolveConflict.isPending} onClick={() => resolveConflict.mutate({ conflictId: conflict.conflict_id, resolution: 'dismiss_both' })}>都不记</button>
                </footer>
              </article>
            ))}
          </div>
        )}

        {(memories.isPending || conflicts.isPending) && <LoadingState label="正在读取本地教学记忆" />}
        <div className="learner-memory-list">
          {memories.data?.map((memory) => (
            <article key={memory.memory_id}>
              {editingMemoryId === memory.memory_id ? (
                <form onSubmit={(event) => {
                  event.preventDefault()
                  if (memoryDraft.trim()) updateMemory.mutate({ memory, statement: memoryDraft.trim() })
                }}>
                  <label>修改这条记忆
                    <textarea value={memoryDraft} onChange={(event) => setMemoryDraft(event.target.value)} maxLength={2000} autoFocus />
                  </label>
                  <footer>
                    <button className="button ghost" type="button" onClick={() => setEditingMemoryId(null)}><X size={15} />取消</button>
                    <button className="button primary" type="submit" disabled={!memoryDraft.trim() || updateMemory.isPending}><Check size={15} />保存</button>
                  </footer>
                </form>
              ) : (
                <>
                  <div className="learner-memory-copy">
                    <span>{memoryTypeLabel(memory)} · {memorySourceLabel(memory.source_kind)}</span>
                    <strong>{memory.statement}</strong>
                    <small>{memory.expires_at ? `${friendlyDate(memory.expires_at)} 后不再使用` : '持续用于相关教学对话'}</small>
                    <MemoryHistory memoryId={memory.memory_id} />
                  </div>
                  <div className="learner-memory-actions">
                    <button type="button" onClick={() => {
                      setEditingMemoryId(memory.memory_id)
                      setMemoryDraft(memory.statement)
                    }}><Pencil size={15} />修改</button>
                    <button className="danger" type="button" disabled={deleteMemory.isPending} onClick={() => confirmForget(memory)}><Trash2 size={15} />忘记</button>
                  </div>
                </>
              )}
            </article>
          ))}
          {!memories.isPending && memories.data?.length === 0 && (
            <p className="settings-empty-line">老师还没有保存任何长期信息。对话中的建议只有经过你确认才会进入这里。</p>
          )}
        </div>
        {(learningModel.error || memories.error || conflicts.error || mutationError) && (
          <ErrorState error={learningModel.error ?? memories.error ?? conflicts.error ?? mutationError} />
        )}
      </section>
    </div>
  )
}

function MemoryHistory({ memoryId }: { memoryId: string }) {
  const [open, setOpen] = useState(false)
  const revisions = useQuery({
    queryKey: ['learner-memory-revisions', memoryId],
    queryFn: () => api<LearnerMemoryRevision[]>(`/api/v1/learner-memories/${memoryId}/revisions?limit=20`),
    enabled: open,
  })
  return (
    <details className="memory-history" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary><History size={13} />修改记录</summary>
      {revisions.isPending && open && <small>正在读取…</small>}
      {revisions.data?.map((revision) => (
        <p key={`${revision.revision}-${String(revision.changed_at)}`}>
          <span>{friendlyDate(String(revision.changed_at)) ?? `版本 ${revision.revision}`}</span>
          <strong>{revision.statement}</strong>
        </p>
      ))}
    </details>
  )
}
