import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MaterialComposer } from './MaterialComposer'

afterEach(cleanup)

describe('MaterialComposer keyboard behaviour', () => {
  it('sends with Enter and keeps Shift+Enter for a new line', async () => {
    const onSend = vi.fn(async () => undefined)
    render(<MaterialComposer onSend={onSend} compact />)
    const input = screen.getByRole('textbox', { name: '向老师提问' })

    fireEvent.change(input, { target: { value: '第一行' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()

    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => expect(onSend).toHaveBeenCalledWith('第一行', []))
  })

  it('adds a pasted screenshot to the next message', async () => {
    const onSend = vi.fn(async () => undefined)
    render(<MaterialComposer onSend={onSend} compact />)
    const input = screen.getByRole('textbox', { name: '向老师提问' })
    const screenshot = new File(['pixels'], 'image.png', { type: 'image/png' })

    fireEvent.paste(input, {
      clipboardData: {
        items: [{
          kind: 'file',
          type: 'image/png',
          getAsFile: () => screenshot,
        }],
      },
    })

    expect(await screen.findByText(/screenshot-/)).toBeInTheDocument()
    fireEvent.change(input, { target: { value: '请解释截图里的阅读题' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(onSend).toHaveBeenCalledWith(
        '请解释截图里的阅读题',
        [expect.objectContaining({ type: 'image/png' })],
      )
    })
  })
})
