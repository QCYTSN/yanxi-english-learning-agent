import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { Shell } from './Shell'
import { SaveState } from './Common'

describe('accessible application shell', () => {
  it('provides navigation, a skip link and visible save status', () => {
    render(
      <MemoryRouter>
        <Shell><SaveState state="saved" /></Shell>
      </MemoryRouter>,
    )
    expect(screen.getByRole('navigation', { name: '主要导航' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '跳到主要内容' })).toHaveAttribute('href', '#main-content')
    expect(screen.getByRole('status')).toHaveTextContent('已保存到本地')
  })
})
