import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, type Bootstrap } from './api/client'
import { ErrorState, LoadingState } from './components/Common'
import { Shell } from './components/Shell'
import { FeedbackPage } from './pages/FeedbackPage'
import { HistoryPage } from './pages/HistoryPage'
import { LibraryPage } from './pages/LibraryPage'
import { PracticePage } from './pages/PracticePage'
import { ReadingWorkspace } from './pages/ReadingWorkspace'
import { SettingsPage } from './pages/SettingsPage'
import { TodayPage } from './pages/TodayPage'
import { WritingWorkspace } from './pages/WritingWorkspace'

export function App({ startupError = null }: { startupError?: Error | null }) {
  const bootstrap = useQuery({
    queryKey: ['bootstrap'],
    queryFn: () => api<Bootstrap>('/api/v1/bootstrap'),
    enabled: !startupError,
  })

  if (startupError) return <StandaloneError error={startupError} />
  if (bootstrap.isPending) return <div className="standalone-state"><LoadingState label="正在连接本地学习服务" /></div>
  if (bootstrap.isError) return <StandaloneError error={bootstrap.error} />
  if (bootstrap.data.setup_required) {
    return (
      <div className="standalone-state">
        <div className="setup-card">
          <p className="eyebrow">首次设置</p>
          <h1>本地学习目录尚未初始化</h1>
          <p>运行 <code>ielts-coach init</code> 后刷新页面。E1 设置表单接入前，系统不会静默创建或覆盖学习数据。</p>
          <button onClick={() => void bootstrap.refetch()}>重新检查</button>
        </div>
      </div>
    )
  }

  return (
    <Shell>
      <Routes>
        <Route path="/today" element={<TodayPage bootstrap={bootstrap.data} />} />
        <Route path="/practice" element={<PracticePage />} />
        <Route path="/practice/writing/:sessionId" element={<WritingWorkspace />} />
        <Route path="/practice/reading/:sessionId" element={<ReadingWorkspace />} />
        <Route path="/feedback/:sessionId" element={<FeedbackPage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage bootstrap={bootstrap.data} />} />
        <Route path="*" element={<Navigate to="/today" replace />} />
      </Routes>
    </Shell>
  )
}

function StandaloneError({ error }: { error: unknown }) {
  return (
    <div className="standalone-state">
      <ErrorState error={error} action={<p>请从终端重新运行 <code>ielts-coach ui start</code>。</p>} />
    </div>
  )
}

