import { render, screen, within } from '@testing-library/react'
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
    expect(screen.getByRole('navigation', { name: '学习导航' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '跳到主要内容' })).toHaveAttribute('href', '#main-content')
    expect(screen.getByRole('status')).toHaveTextContent('已保存到本地')
  })

  it('shows a clickable settings parent and the current settings section', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/settings/models']}>
        <Shell><div>模型设置内容</div></Shell>
      </MemoryRouter>,
    )
    const banner = container.querySelector('header')
    expect(banner).not.toBeNull()
    if (!banner) return
    expect(within(banner).getByRole('link', { name: '设置' })).toHaveAttribute('href', '/settings')
    expect(within(banner).getByText('模型服务')).toBeInTheDocument()
  })
})
