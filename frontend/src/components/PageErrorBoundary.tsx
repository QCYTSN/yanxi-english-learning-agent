import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'

type BoundaryState = { error: Error | null }

export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation()
  return <PageErrorBoundary key={location.pathname}>{children}</PageErrorBoundary>
}

export class PageErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page rendering failed', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="page page-narrow">
        <section className="error-state" role="alert">
          <p className="eyebrow">页面恢复</p>
          <h2>这个页面的数据格式暂时不兼容</h2>
          <p>学习数据没有被修改。请返回首页；如果刚刚升级过应用，请关闭旧窗口后重新启动。</p>
          <details>
            <summary>查看技术信息</summary>
            <code>{this.state.error.message}</code>
          </details>
          <div className="row-actions">
            <Link className="button primary" to="/today">返回首页</Link>
            <button className="button secondary" onClick={() => window.location.reload()}>重新加载</button>
          </div>
        </section>
      </div>
    )
  }
}
