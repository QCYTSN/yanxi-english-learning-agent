import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThreadActions } from './ThreadActions'

const thread = {
  thread_id: 'thread_test',
  title: 'Original title',
}

function renderActions(props: { onDeleted?: () => void } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ThreadActions thread={thread} {...props} />
    </QueryClientProvider>,
  )
}

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ThreadActions', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renames a conversation from the action menu', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({
      ...thread,
      title: 'Reading review',
      module: 'mixed',
      status: 'active',
      model_provider_id: null,
      source_context: {},
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:01:00Z',
      messages: [],
      attachments: [],
      message_count: 0,
      attachment_count: 0,
      last_message_preview: '',
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderActions()

    fireEvent.click(screen.getByRole('button', { name: '管理对话：Original title' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '重命名' }))
    fireEvent.change(screen.getByRole('textbox', { name: '新标题' }), {
      target: { value: 'Reading review' },
    })
    fireEvent.click(screen.getByRole('button', { name: '保存标题' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/study-threads/thread_test',
      expect.objectContaining({ method: 'PATCH' }),
    ))
  })

  it('requires confirmation before deleting a conversation', async () => {
    const onDeleted = vi.fn()
    const fetchMock = vi.fn(async () => jsonResponse({
      thread_id: thread.thread_id,
      deleted: true,
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderActions({ onDeleted })

    fireEvent.click(screen.getByRole('button', { name: '管理对话：Original title' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '删除对话' }))
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))

    await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/study-threads/thread_test',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })
})
