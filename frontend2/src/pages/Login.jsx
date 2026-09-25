import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowRight, Phone, Lock, Eye, EyeOff } from 'lucide-react'

export default function Login() {
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await axios.post('/api/v1/users/auth/login/', {
        phone: phone.trim(),
        password,
      })
      localStorage.setItem('access', res.data.access)
      localStorage.setItem('refresh', res.data.refresh)
      navigate('/dashboard')
    } catch {
      setError('Неверный телефон или пароль')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ fontFamily: 'Rubik, sans-serif', minHeight: '100vh', display: 'grid', gridTemplateColumns: '1fr 1fr', overflow: 'hidden' }}>

      {/* ЛЕВАЯ */}
      <div style={{ background: '#FDF6F0', display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '56px 64px', position: 'relative', overflow: 'hidden' }}>
        <svg style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0 }} viewBox="0 0 720 900" preserveAspectRatio="xMidYMid slice">
          <path d="M-50,300 C150,100 350,500 550,200" fill="none" stroke="#E8998D" strokeWidth="1" opacity="0.08"/>
          <path d="M-50,500 C150,300 350,700 550,400" fill="none" stroke="#E8998D" strokeWidth="1" opacity="0.06"/>
          <circle cx="600" cy="150" r="200" fill="none" stroke="#E8998D" strokeWidth="1" opacity="0.05"/>
          <circle cx="80" cy="700" r="150" fill="none" stroke="#E8998D" strokeWidth="1" opacity="0.05"/>
        </svg>

        <div style={{ position: 'relative', zIndex: 1 }}>
          {/* Logo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 28 }}>
            <div style={{ width: 36, height: 36, background: 'linear-gradient(135deg,#E8998D,#C97B6E)', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="#fff">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
              </svg>
            </div>
            <span style={{ fontSize: 18, fontWeight: 700, color: '#0A0A0A' }}>KidsCRM</span>
          </div>

          {/* Title */}
          <div style={{ fontSize: 36, fontWeight: 700, lineHeight: 1.2, letterSpacing: '-0.5px', color: '#0A0A0A', marginBottom: 16 }}>
            Управляйте<br />центром<br />в одном месте
          </div>

          <p style={{ fontSize: 15, color: '#6B7280', lineHeight: 1.7, marginBottom: 40, maxWidth: 340 }}>
            Замените WhatsApp и Excel. Дети, расписание, абонементы и оплаты — всё под контролем.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {['База учеников и родителей', 'Расписание и посещаемость', 'Абонементы и оплаты', 'Аналитика и отчёты'].map(f => (
              <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#374151', fontWeight: 500 }}>
                <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'linear-gradient(135deg,#E8998D,#C97B6E)', flexShrink: 0 }} />
                {f}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ПРАВАЯ */}
      <div style={{ background: 'linear-gradient(160deg,#C97B6E 0%,#E8998D 50%,#F5C6BD 100%)', display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: 64, position: 'relative', overflow: 'hidden' }}>
        <svg style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0, opacity: 0.08 }} viewBox="0 0 720 900" preserveAspectRatio="xMidYMid slice">
          <path d="M-50,200 C150,0 350,400 550,150" fill="none" stroke="#fff" strokeWidth="2"/>
          <path d="M-50,450 C150,250 350,650 550,400" fill="none" stroke="#fff" strokeWidth="1.5"/>
          <circle cx="600" cy="100" r="200" fill="none" stroke="#fff" strokeWidth="1"/>
          <circle cx="100" cy="800" r="150" fill="none" stroke="#fff" strokeWidth="1"/>
        </svg>

        <div style={{ position: 'relative', zIndex: 1, maxWidth: 380, margin: '0 auto', width: '100%' }}>
          <h2 style={{ fontSize: 24, fontWeight: 700, color: '#fff', marginBottom: 8, letterSpacing: '-0.3px' }}>Вход в систему</h2>
          <p style={{ fontSize: 14, color: 'rgba(255,255,255,0.6)', marginBottom: 36, lineHeight: 1.6 }}>
            Введите телефон и пароль. Если у вас нет доступа — обратитесь к администратору.
          </p>

          <form onSubmit={handleSubmit}>
            {/* Phone */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'rgba(255,255,255,0.6)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                Телефон
              </label>
              <div style={{ position: 'relative' }}>
                <Phone size={15} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.4)' }} />
                <input
                  type="tel"
                  value={phone}
                  onChange={e => setPhone(e.target.value.replace(/[^\d+\s\-()]/g, ''))}
                  placeholder="+7 701 234 56 78"
                  required
                  style={{ width: '100%', padding: '13px 14px 13px 42px', background: 'rgba(255,255,255,0.08)', border: '1.5px solid rgba(255,255,255,0.12)', borderRadius: 10, fontFamily: 'Rubik', fontSize: 14, color: '#fff', outline: 'none' }}
                />
              </div>
            </div>

            {/* Password */}
            <div style={{ marginBottom: 20 }}>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 6, color: 'rgba(255,255,255,0.6)', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                Пароль
              </label>
              <div style={{ position: 'relative' }}>
                <Lock size={15} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'rgba(255,255,255,0.4)' }} />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="Введите пароль"
                  required
                  style={{ width: '100%', padding: '13px 44px 13px 42px', background: 'rgba(255,255,255,0.08)', border: '1.5px solid rgba(255,255,255,0.12)', borderRadius: 10, fontFamily: 'Rubik', fontSize: 14, color: '#fff', outline: 'none' }}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={{ position: 'absolute', right: 14, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'rgba(255,255,255,0.4)', display: 'flex', padding: 2 }}
                >
                  {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                </button>
              </div>
            </div>

            {error && (
              <p style={{ fontSize: 12, color: '#FCA5A5', marginBottom: 8 }}>{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              style={{ width: '100%', padding: 14, background: '#fff', color: '#E8998D', border: 'none', borderRadius: 10, fontFamily: 'Rubik', fontSize: 15, fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer', marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, opacity: loading ? 0.6 : 1 }}
            >
              {loading ? 'Входим...' : <>Войти <ArrowRight size={16} /></>}
            </button>
          </form>

          <p style={{ marginTop: 32, fontSize: 12, color: 'rgba(255,255,255,0.3)', textAlign: 'center' }}>
            © 2026 KidsCRM. Все права защищены.
          </p>
        </div>
      </div>
    </div>
  )
}
