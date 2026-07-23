import { useQuery } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, type Bootstrap } from './api/client'
import { ErrorState, LoadingState } from './components/Common'
import { Shell } from './components/Shell'
import { FeedbackPage } from './pages/FeedbackPage'
import { AssessmentRunnerPage } from './pages/AssessmentRunnerPage'
import { DiagnosticPage } from './pages/DiagnosticPage'
import { HistoryPage } from './pages/HistoryPage'
import { LibraryPage } from './pages/LibraryPage'
import { ListeningWorkspace } from './pages/ListeningWorkspace'
import { OnboardingPage } from './pages/OnboardingPage'
import { PracticePage } from './pages/PracticePage'
import { ReadingWorkspace } from './pages/ReadingWorkspace'
import { SettingsPage } from './pages/SettingsPage'
import { SpeakingWorkspace } from './pages/SpeakingWorkspace'
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
          <p>请关闭此页面后重新双击桌面的 IELTS Study Desk。快捷方式会创建缺少的本地目录，不需要编辑配置文件。</p>
          <button onClick={() => void bootstrap.refetch()}>重新检查</button>
        </div>
      </div>
    )
  }
  if (bootstrap.data.onboarding?.status !== 'ready') {
    return <OnboardingPage bootstrap={bootstrap.data} />
  }

  return (
    <Shell>
      <Routes>
        <Route path="/today" element={<TodayPage bootstrap={bootstrap.data} />} />
        <Route path="/practice" element={<PracticePage />} />
        <Route path="/assessment/:runId" element={<AssessmentRunnerPage />} />
        <Route path="/practice/writing/:sessionId" element={<WritingWorkspace />} />
        <Route path="/practice/reading/:sessionId" element={<ReadingWorkspace />} />
        <Route path="/practice/listening" element={<ListeningWorkspace />} />
        <Route path="/practice/listening/:sessionId" element={<ListeningWorkspace />} />
        <Route path="/practice/speaking" element={<SpeakingWorkspace />} />
        <Route path="/feedback/:sessionId" element={<FeedbackPage />} />
        <Route path="/diagnostic" element={<DiagnosticPage />} />
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
