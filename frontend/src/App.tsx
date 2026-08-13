import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { api, type Bootstrap } from './api/client'
import { ErrorState, LoadingState } from './components/Common'
import { RouteErrorBoundary } from './components/PageErrorBoundary'
import { Shell } from './components/Shell'
import { OnboardingPage } from './pages/OnboardingPage'

const DiagnosticPage = lazy(() => import('./pages/DiagnosticPage').then((module) => ({ default: module.DiagnosticPage })))
const FeedbackPage = lazy(() => import('./pages/FeedbackPage').then((module) => ({ default: module.FeedbackPage })))
const HistoryPage = lazy(() => import('./pages/HistoryPage').then((module) => ({ default: module.HistoryPage })))
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((module) => ({ default: module.LibraryPage })))
const ContentStudioPage = lazy(() => import('./pages/LibraryPage').then((module) => ({ default: module.ContentStudioPage })))
const ConversationsPage = lazy(() => import('./pages/ConversationsPage').then((module) => ({ default: module.ConversationsPage })))
const ListeningWorkspace = lazy(() => import('./pages/ListeningWorkspace').then((module) => ({ default: module.ListeningWorkspace })))
const PracticePage = lazy(() => import('./pages/PracticePage').then((module) => ({ default: module.PracticePage })))
const ReadingWorkspace = lazy(() => import('./pages/ReadingWorkspace').then((module) => ({ default: module.ReadingWorkspace })))
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })))
const SpeakingWorkspace = lazy(() => import('./pages/SpeakingWorkspace').then((module) => ({ default: module.SpeakingWorkspace })))
const StudyThreadPage = lazy(() => import('./pages/StudyThreadPage').then((module) => ({ default: module.StudyThreadPage })))
const VocabularyPage = lazy(() => import('./pages/VocabularyPage').then((module) => ({ default: module.VocabularyPage })))
const TodayPage = lazy(() => import('./pages/TodayPage').then((module) => ({ default: module.TodayPage })))
const WritingWorkspace = lazy(() => import('./pages/WritingWorkspace').then((module) => ({ default: module.WritingWorkspace })))

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
          <p>请关闭此页面后重新双击桌面的言蹊。快捷方式会创建缺少的本地目录，不需要编辑配置文件。</p>
          <button onClick={() => void bootstrap.refetch()}>重新检查</button>
        </div>
      </div>
    )
  }
  if (bootstrap.data.onboarding?.status !== 'ready') {
    return <OnboardingPage bootstrap={bootstrap.data} />
  }

  return (
    <Shell bootstrap={bootstrap.data}>
      <RouteErrorBoundary>
        <Suspense fallback={<div className="route-loading"><LoadingState label="正在打开学习工作区" /></div>}>
          <Routes>
            <Route path="/today" element={<TodayPage bootstrap={bootstrap.data} />} />
            <Route path="/practice" element={<PracticePage />} />
            <Route path="/practice/writing/:sessionId" element={<WritingWorkspace />} />
            <Route path="/practice/reading/:sessionId" element={<ReadingWorkspace />} />
            <Route path="/practice/listening" element={<ListeningWorkspace />} />
            <Route path="/practice/listening/:sessionId" element={<ListeningWorkspace />} />
            <Route path="/practice/speaking" element={<SpeakingWorkspace />} />
            <Route path="/study/:threadId" element={<StudyThreadPage />} />
            <Route path="/conversations" element={<ConversationsPage />} />
            <Route path="/feedback/:sessionId" element={<FeedbackPage />} />
            <Route path="/diagnostic" element={<DiagnosticPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/content-studio" element={<ContentStudioPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/vocabulary" element={<VocabularyPage />} />
            <Route path="/settings" element={<SettingsPage bootstrap={bootstrap.data} />} />
            <Route path="/settings/:section" element={<SettingsPage bootstrap={bootstrap.data} />} />
            <Route path="*" element={<Navigate to="/today" replace />} />
          </Routes>
        </Suspense>
      </RouteErrorBoundary>
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
