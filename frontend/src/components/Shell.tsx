import { BookOpen, Clock3, History, Home, Library, Settings } from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'
import { useEffect, useRef, type PropsWithChildren } from 'react'

const navigation = [
  { to: '/today', label: '今日学习', icon: Home },
  { to: '/practice', label: '开始练习', icon: BookOpen },
  { to: '/library', label: '内容与题库', icon: Library },
  { to: '/history', label: '历史与进步', icon: History },
  { to: '/settings', label: '设置', icon: Settings },
]

export function Shell({ children }: PropsWithChildren) {
  const location = useLocation()
  const mainRef = useRef<HTMLElement>(null)

  useEffect(() => {
    mainRef.current?.focus()
  }, [location.pathname])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">I</span>
          <span><strong>IELTS</strong><small>Study Desk</small></span>
        </div>
        <nav aria-label="主要导航">
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              <Icon size={19} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-note">
          <Clock3 size={16} aria-hidden="true" />
          <span>所有正式记录保存在本地</span>
        </div>
      </aside>
      <main ref={mainRef} id="main-content" className="main-content" tabIndex={-1}>{children}</main>
    </div>
  )
}
