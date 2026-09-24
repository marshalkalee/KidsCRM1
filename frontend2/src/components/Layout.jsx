import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Users, UsersRound, Calendar,
  CheckSquare, CreditCard, Settings, LogOut,
  Bell, Search
} from 'lucide-react'

const navGroups = [
  {
    label: 'Меню',
    items: [
      { to: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
      { to: '/children', label: 'Дети', icon: Users },
      { to: '/groups', label: 'Группы', icon: UsersRound },
      { to: '/schedule', label: 'Расписание', icon: Calendar },
      { to: '/attendance', label: 'Посещаемость', icon: CheckSquare },
      { to: '/payments', label: 'Оплаты', icon: CreditCard },
    ]
  },
  {
    label: 'Другое',
    items: [
      { to: '/settings', label: 'Настройки', icon: Settings },
    ]
  }
]

export default function Layout() {
  const navigate = useNavigate()

  function handleLogout() {
    localStorage.removeItem('access')
    localStorage.removeItem('refresh')
    navigate('/login')
  }

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#F8F9FF', fontFamily: 'Rubik, sans-serif' }}>

      {/* SIDEBAR */}
      <aside style={{
        width: 240,
        background: '#fff',
        borderRight: '1px solid #F0F0F5',
        display: 'flex',
        flexDirection: 'column',
        flexShrink: 0,
      }}>
        {/* Logo */}
        <div style={{ padding: '24px 20px', borderBottom: '1px solid #F0F0F5' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 38, height: 38,
              background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
              borderRadius: 10,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <span style={{ color: '#fff', fontWeight: 700, fontSize: 16 }}>K</span>
            </div>
            <span style={{ fontWeight: 700, fontSize: 17, color: '#1A1A2E' }}>KidsCRM</span>
          </div>
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '16px 12px', overflowY: 'auto' }}>
          {navGroups.map(group => (
            <div key={group.label} style={{ marginBottom: 24 }}>
              <p style={{
                fontSize: 11, fontWeight: 600,
                color: '#9CA3AF',
                textTransform: 'uppercase',
                letterSpacing: '0.08em',
                padding: '0 8px',
                marginBottom: 8,
              }}>
                {group.label}
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {group.items.map(item => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    style={({ isActive }) => ({
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '10px 12px',
                      borderRadius: 10,
                      textDecoration: 'none',
                      fontSize: 14,
                      fontWeight: isActive ? 600 : 400,
                      color: isActive ? '#C97B6E' : '#6B7280',
                      background: isActive ? '#FDF0EE' : 'transparent',
                      transition: 'all 0.15s',
                    })}
                  >
                    <item.icon size={18} />
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* User */}
        {/* Logout only */}
    <div style={{ padding: '12px', borderTop: '1px solid #F0F0F5' }}>
      <button
        onClick={handleLogout}
        style={{
        width: '100%',
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 12px',
        borderRadius: 10,
        border: 'none',
        background: 'transparent',
        cursor: 'pointer',
        fontSize: 14,
        color: '#9CA3AF',
        fontFamily: 'Rubik',
        }}
      >
        <LogOut size={16} />
        Выйти
      </button>
    </div>
      </aside>

      {/* MAIN */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* TOPBAR */}
        <header style={{
          height: 64,
          background: '#fff',
          borderBottom: '1px solid #F0F0F5',
          display: 'flex', alignItems: 'center',
          padding: '0 24px',
          gap: 16,
          flexShrink: 0,
        }}>
          <div style={{
            flex: 1,
            display: 'flex', alignItems: 'center', gap: 10,
            background: '#F8F9FF',
            border: '1px solid #F0F0F5',
            borderRadius: 10,
            padding: '8px 14px',
            maxWidth: 360,
          }}>
            <Search size={16} style={{ color: '#9CA3AF', flexShrink: 0 }} />
            <input
              placeholder="Поиск учеников, родителей..."
              style={{
                border: 'none', background: 'transparent',
                outline: 'none', fontSize: 13,
                color: '#1A1A2E', width: '100%',
                fontFamily: 'Rubik',
              }}
            />
          </div>
          <button style={{
            width: 38, height: 38,
            borderRadius: 10,
            border: '1px solid #F0F0F5',
            background: '#fff',
            cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            position: 'relative',
          }}>
            <Bell size={18} style={{ color: '#6B7280' }} />
            <span style={{
              position: 'absolute', top: 8, right: 8,
              width: 6, height: 6,
              borderRadius: '50%',
              background: '#E8998D',
            }} />
          </button>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            cursor: 'pointer',
          }}>
            <div style={{
              width: 36, height: 36,
              background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
              borderRadius: '50%',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <span style={{ color: '#fff', fontWeight: 700, fontSize: 13 }}>А</span>
            </div>
            <div>
              <p style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', margin: 0 }}>Айгуль</p>
              <p style={{ fontSize: 11, color: '#9CA3AF', margin: 0 }}>Владелец</p>
            </div>
          </div>
        </header>

        {/* PAGE CONTENT */}
        <main style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
