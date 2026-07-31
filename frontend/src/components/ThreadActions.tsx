import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Ellipsis, PencilLine, Trash2, X } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { api, jsonBody, type StudyThread } from '../api/client'
import { ErrorState } from './Common'

type DialogMode = 'rename' | 'delete' | null

export function ThreadActions({
  thread,
  compact = false,
  onRenamed,
  onDeleted,
}: {
  thread: Pick<StudyThread, 'thread_id' | 'title'>
  compact?: boolean
  onRenamed?: (thread: StudyThread) => void
  onDeleted?: () => void
}) {
  const queryClient = useQueryClient()
  const [menuOpen, setMenuOpen] = useState(false)
  const [dialog, setDialog] = useState<DialogMode>(null)
  const [title, setTitle] = useState(thread.title)

  useEffect(() => setTitle(thread.title), [thread.title])
  useEffect(() => {
    if (!menuOpen && !dialog) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        setDialog(null)
      }
    }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [dialog, menuOpen])

  const rename = useMutation({
    mutationFn: () => api<StudyThread>(`/api/v1/study-threads/${thread.thread_id}`, {
      method: 'PATCH',
      body: jsonBody({ title: title.trim() }),
    }),
    onSuccess: async (renamed) => {
      queryClient.setQueryData(['study-thread', thread.thread_id], renamed)
      await queryClient.invalidateQueries({ queryKey: ['study-threads'] })
      setDialog(null)
      onRenamed?.(renamed)
    },
  })
  const remove = useMutation({
    mutationFn: () => api<{ thread_id: string; deleted: boolean }>(
      `/api/v1/study-threads/${thread.thread_id}`,
      { method: 'DELETE' },
    ),
    onSuccess: async () => {
      setDialog(null)
      onDeleted?.()
      queryClient.removeQueries({ queryKey: ['study-thread', thread.thread_id] })
      await queryClient.invalidateQueries({ queryKey: ['study-threads'] })
    },
  })

  function open(next: Exclude<DialogMode, null>) {
    setTitle(thread.title)
    setMenuOpen(false)
    setDialog(next)
  }

  function submitRename(event: FormEvent) {
    event.preventDefault()
    if (title.trim() && title.trim() !== thread.title) rename.mutate()
  }

  const dialogContent = dialog === 'rename' ? (
    <form className={compact ? 'thread-inline-form' : undefined} onSubmit={submitRename}>
      {compact ? (
        <div className="thread-inline-heading">
          <strong>重命名</strong>
          <button type="button" aria-label="关闭" onClick={() => setDialog(null)}>
            <X size={14} />
          </button>
        </div>
      ) : (
        <>
          <p className="eyebrow">对话标题</p>
          <h2 id="thread-rename-title">重命名对话</h2>
          <p>使用便于以后搜索和继续学习的标题。</p>
        </>
      )}
      <label>
        {!compact && <span>新标题</span>}
        <input
          autoFocus
          aria-label="新标题"
          maxLength={120}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      {rename.error && <ErrorState error={rename.error} />}
      <footer>
        <button className="button secondary" type="button" onClick={() => setDialog(null)}>
          取消
        </button>
        <button
          className="button primary"
          type="submit"
          disabled={!title.trim() || title.trim() === thread.title || rename.isPending}
        >
          {rename.isPending ? '正在保存…' : compact ? '保存' : '保存标题'}
        </button>
      </footer>
    </form>
  ) : dialog === 'delete' ? (
    <div className={compact ? 'thread-inline-delete' : undefined}>
      {compact ? (
        <div className="thread-inline-heading">
          <strong>删除这条对话？</strong>
          <button type="button" aria-label="关闭" onClick={() => setDialog(null)}>
            <X size={14} />
          </button>
        </div>
      ) : (
        <>
          <p className="eyebrow danger">永久删除</p>
          <h2 id="thread-delete-title">删除“{thread.title}”？</h2>
        </>
      )}
      <p>{compact ? '消息和附件将被删除，无法撤销。' : '这会删除本对话中的消息和附件，且无法撤销；正式学习 Session 不受影响。'}</p>
      {remove.error && <ErrorState error={remove.error} />}
      <footer>
        <button className="button secondary" type="button" onClick={() => setDialog(null)}>
          取消
        </button>
        <button
          className="button danger"
          type="button"
          disabled={remove.isPending}
          onClick={() => remove.mutate()}
        >
          {remove.isPending ? '正在删除…' : compact ? '删除' : '确认删除'}
        </button>
      </footer>
    </div>
  ) : null

  return (
    <div className={`thread-actions${compact ? ' compact' : ''}`}>
      <button
        className="thread-actions-trigger"
        type="button"
        aria-label={`管理对话：${thread.title}`}
        aria-expanded={menuOpen}
        title="管理对话"
        onClick={() => setMenuOpen((current) => !current)}
      >
        <Ellipsis size={compact ? 16 : 18} />
      </button>
      {menuOpen && (
        <>
          <button
            className="thread-actions-dismiss"
            type="button"
            aria-label="关闭对话菜单"
            onClick={() => setMenuOpen(false)}
          />
          <div className="thread-actions-popover" role="menu">
            <button type="button" role="menuitem" onClick={() => open('rename')}>
              <PencilLine size={15} />
              重命名
            </button>
            <button className="danger" type="button" role="menuitem" onClick={() => open('delete')}>
              <Trash2 size={15} />
              删除对话
            </button>
          </div>
        </>
      )}

      {dialog && compact && (
        <>
          <button
            className="thread-actions-dismiss"
            type="button"
            aria-label="关闭对话操作"
            onClick={() => setDialog(null)}
          />
          <section
            className="thread-inline-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={dialog === 'rename' ? '重命名对话' : '删除对话'}
          >
            {dialogContent}
          </section>
        </>
      )}

      {dialog && !compact && (
        <div
          className="thread-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDialog(null)
          }}
        >
          <section
            className="thread-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby={`thread-${dialog}-title`}
          >
            <button
              className="thread-dialog-close"
              type="button"
              aria-label="关闭"
              onClick={() => setDialog(null)}
            >
              <X size={18} />
            </button>
            {dialogContent}
          </section>
        </div>
      )}
    </div>
  )
}
