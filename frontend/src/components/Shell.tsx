import {
  BookOpenText,
  BookMarked,
  ChartNoAxesCombined,
  ChevronRight,
  House,
  LibraryBig,
  MessageSquareText,
  Plus,
  Settings2,
} from 'lucide-react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useEffect, useRef, type PropsWithChildren } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Bootstrap, type StudyThread } from '../api/client'
import { ModelSwitcher } from './ModelSwitcher'
import { ThreadActions } from './ThreadActions'

const navigation = [
  { to: '/today', label: '今天', icon: House },
  { to: '/practice', label: '练习', icon: BookOpenText },
  { to: '/library', label: '资料库', icon: LibraryBig },
  { to: '/history', label: '进步', icon: ChartNoAxesCombined },
]

const routeLabels = [
  ['/practice/writing', '写作工作区'],
  ['/practice/reading', '阅读工作区'],
  ['/practice/listening', '听力工作区'],
  ['/practice/speaking', '口语工作区'],
  ['/assessment', '完整模考'],
  ['/feedback', '反馈与修订'],
  ['/diagnostic', '能力摸底'],
  ['/content-studio', '内容工作台'],
  ['/conversations', '学习对话'],
  ['/study', '学习对话'],
  ['/practice', '练习'],
  ['/library', '资料库'],
  ['/history', '进步'],
  ['/settings', '设置'],
  ['/today', '今天'],
] as const

const settingsSectionLabels: Record<string, string> = {
  profile: '学习档案',
  models: '模型服务',
  data: '本地数据',
  trust: '教学标准',
  advanced: '高级',
  system: '系统状态',
}

export function Shell({ children, bootstrap }: PropsWithChildren<{ bootstrap?: Bootstrap }>) {
  const location = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const routeLabel = routeLabels.find(([prefix]) => location.pathname.startsWith(prefix))?.[1] ?? '学习'
  const settingsSection = location.pathname.match(/^\/settings\/([^/]+)\/?$/)?.[1]
  const settingsSectionLabel = settingsSection ? settingsSectionLabels[settingsSection] : null
  const dateLabel = new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
    weekday: 'short',
  }).format(new Date())

  useEffect(() => {
    mainRef.current?.focus()
  }, [location.pathname])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <Link className="brand" to="/today" aria-label="IELTS Study Desk 首页">
          <span className="brand-mark" aria-hidden="true"><BookMarked size={24} /></span>
          <span className="brand-copy"><strong>IELTS</strong><small>Study Desk</small></span>
        </Link>

        <nav className="primary-nav" aria-label="学习导航">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
            >
              <Icon size={19} strokeWidth={1.75} aria-hidden="true" />
              <span><strong>{label}</strong></span>
            </NavLink>
          ))}
        </nav>

        {bootstrap && <RecentStudyThreads currentPath={location.pathname} />}

        <NavLink
          to="/settings"
          className={({ isActive }) => `nav-link nav-settings${isActive ? ' active' : ''}`}
        >
          <Settings2 size={19} strokeWidth={1.75} aria-hidden="true" />
          <span><strong>设置</strong></span>
        </NavLink>
      </aside>

      <div className="workspace-shell">
        <header className="workspace-bar">
          <div className="workspace-context">
            <span>IELTS Academic</span>
            <ChevronRight size={14} aria-hidden="true" />
            {settingsSectionLabel ? (
              <>
                <Link to="/settings">设置</Link>
                <ChevronRight size={14} aria-hidden="true" />
                <strong>{settingsSectionLabel}</strong>
              </>
            ) : (
              <strong>{routeLabel}</strong>
            )}
          </div>
          <div className="workspace-tools">
            {bootstrap && <ModelSwitcher bootstrapProviders={bootstrap.model_providers} />}
            <time className="workspace-date">{dateLabel}</time>
          </div>
        </header>
        <main ref={mainRef} id="main-content" className="main-content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  )
}

function RecentStudyThreads({ currentPath }: { currentPath: string }) {
  const recentThreads = useQuery({
    queryKey: ['study-threads', 'recent'],
    queryFn: () => api<StudyThread[]>('/api/v1/study-threads?limit=6'),
    staleTime: 30_000,
  })
  return (
    <section className="recent-study-threads" aria-label="最近学习对话">
      <header>
        <small>最近对话</small>
        <Link className="recent-thread-new" to="/today" title="开始新对话" aria-label="开始新对话">
          <Plus size={15} />
        </Link>
      </header>
      <div className="recent-thread-list">
        {recentThreads.isPending && (
          <>
            <span className="recent-thread-skeleton" />
            <span className="recent-thread-skeleton" />
          </>
        )}
        {recentThreads.data?.map((thread) => (
          <div
            className={`recent-thread-row${currentPath === `/study/${thread.thread_id}` ? ' active' : ''}`}
            key={thread.thread_id}
          >
            <Link
              className={`recent-thread-link${currentPath === `/study/${thread.thread_id}` ? ' active' : ''}`}
              to={`/study/${thread.thread_id}`}
              title={thread.title}
            >
              <MessageSquareText size={15} strokeWidth={1.65} aria-hidden="true" />
              <span>
                <strong>{thread.title}</strong>
                <small>{threadModuleLabel(thread.module)} · {compactThreadTime(thread.updated_at)}</small>
              </span>
            </Link>
            <ThreadActions thread={thread} compact />
          </div>
        ))}
        {!recentThreads.isPending && !recentThreads.data?.length && (
          <p className="recent-thread-empty">你的雅思提问会保存在这里。</p>
        )}
      </div>
      <Link className="recent-thread-all" to="/conversations">查看全部对话</Link>
    </section>
  )
}

function threadModuleLabel(module: StudyThread['module']) {
  return ({ reading: '阅读', writing: '写作', mixed: '综合' } as const)[module]
}

function compactThreadTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date)
  }
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric',
    day: 'numeric',
  }).format(date)
}
