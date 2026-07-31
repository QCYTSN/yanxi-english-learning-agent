import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MaterialComposer } from './MaterialComposer'

describe('MaterialComposer keyboard behaviour', () => {
  it('sends with Enter and keeps Shift+Enter for a new line', async () => {
    const onSend = vi.fn(async () => undefined)
    render(<MaterialComposer onSend={onSend} compact />)
    const input = screen.getByRole('textbox', { name: '向 IELTS 教师提问' })

    fireEvent.change(input, { target: { value: '第一行' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()

    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onSend).toHaveBeenCalledWith('第一行', []))
  })
})
