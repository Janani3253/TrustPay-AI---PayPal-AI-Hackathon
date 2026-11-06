import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  Activity, Bell, Boxes, ChevronLeft, ChevronRight, CircleAlert, ClipboardCheck,
  FileClock, LayoutDashboard, LogOut, Menu, Search, ShieldCheck, ShoppingBag,
  ShoppingCart, X,
} from 'lucide-react'
import { Brand } from '../common/Brand'
import { useApp } from '../../context/AppContext'
import { logout as logoutFromBackend } from '../../services/authService'
import { getBackendError } from '../../services/backendService'

const links = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/platforms', label: 'Choose platform', icon: Boxes },
  { to: '/products', label: 'Products', icon: Boxes },
  { to: '/shopping-request', label: 'Shopping request', icon: Search },
  { to: '/product-results', label: 'Product results', icon: ShoppingBag },
  { to: '/cart', label: 'Shopping cart', icon: ShoppingCart },
  { to: '/verification', label: 'IntentLock', icon: ShieldCheck },
  { to: '/approval', label: 'Order approval', icon: ClipboardCheck },
  { to: '/transactions', label: 'Transactions', icon: Activity },
  { to: '/audit-log', label: 'Audit log', icon: FileClock },
]

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const { user, setUser, cart, notify } = useApp()
  const navigate = useNavigate()
  const initials = (user?.name ?? 'Alex Morgan').split(' ').map((part) => part[0]).slice(0, 2).join('').toUpperCase()
  const closeMenu = () => setMobileOpen(false)
  const logout = async () => {
    let message: string | null = null
    try {
      await logoutFromBackend()
    } catch (error) {
      message = getBackendError(error, 'The backend could not confirm session revocation.')
    }
    setUser(null)
    notify(message ? `Signed out locally; backend logout failed: ${message}` : 'You have been signed out.', message ? 'error' : 'info')
    navigate('/')
  }

  return (
    <div className={`app-shell ${collapsed ? 'is-collapsed' : ''}`}>
      {mobileOpen && <button className="mobile-backdrop" aria-label="Close navigation" onClick={closeMenu} />}
      <aside className={`sidebar ${mobileOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-brand"><Brand /><button className="icon-btn mobile-close" onClick={closeMenu} aria-label="Close menu"><X size={19} /></button></div>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="side-nav">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={closeMenu} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
              <Icon size={18} /><span>{label}</span>{to === '/cart' && cart.length > 0 && <b className="nav-count">{cart.length}</b>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-note"><ShieldCheck size={18} /><span>IntentLock is active<br /><small>Your intent comes first</small></span></div>
          <div className="profile-row"><span className="avatar">{(user?.name ?? 'AM').slice(0, 1).toUpperCase()}</span><span className="profile-copy"><b>{user?.name ?? 'Alex Morgan'}</b><small>{user?.email ?? 'alex@example.com'}</small></span><button className="icon-btn logout-btn" onClick={logout} title="Log out" aria-label="Log out"><LogOut size={17} /></button></div>
        </div>
        <button className="collapse-btn" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={() => setCollapsed(!collapsed)}>{collapsed ? <ChevronRight size={17} /> : <ChevronLeft size={17} />}</button>
      </aside>
      <section className="app-main">
        <header className="topbar">
          <button className="icon-btn mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={21} /></button>
          <div className="breadcrumb"><span>Workspace</span><span>/</span><b>TrustPay AI</b></div>
          <div className="topbar-right"><span className="secure-pill"><span /> Protected session</span><div className="notification-wrap"><button className="icon-btn notification-btn" aria-label="Notifications" aria-expanded={notificationsOpen} onClick={() => setNotificationsOpen(!notificationsOpen)}><Bell size={18} /><i /></button>{notificationsOpen && <div className="notification-popover"><b>Recent notifications</b><p><CircleAlert size={15} /> Review seller verification before checkout.</p><p><ShieldCheck size={15} /> IntentLock is ready to verify your order.</p></div>}</div><span className="top-avatar">{initials}</span></div>
        </header>
        <main className="main-content"><Outlet /></main>
      </section>
    </div>
  )
}
