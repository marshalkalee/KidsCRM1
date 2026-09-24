import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowRight, Eye, EyeOff } from 'lucide-react'
import { useSession } from '../session/SessionContext'
import { Button, Field, Input } from '../ui'

const FEATURES = [
  'База детей и родителей без дублей',
  'Расписание, группы и посещаемость',
  'Абонементы, оплаты и задолженности',
]

export default function Login() {
  const { status, reload } = useSession()
  const navigate = useNavigate()
  const location = useLocation()
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const next = location.state?.from || '/dashboard'

  if (status === 'ready') return <Navigate to={next} replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await axios.post('/api/v1/users/auth/login/', { phone: phone.trim(), password })
      localStorage.setItem('access', res.data.access)
      localStorage.setItem('refresh', res.data.refresh)
      await reload()
      navigate(next, { replace: true })
    } catch (err) {
      setError(err.response?.status === 429 ? 'Слишком много попыток. Подождите минуту.' : 'Неверный телефон или пароль')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden bg-gradient-to-br from-brand-500 via-brand-400 to-brand-200 p-14 text-white lg:flex lg:flex-col lg:justify-between">
        <svg className="pointer-events-none absolute inset-0 size-full opacity-15" viewBox="0 0 720 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <path d="M-50,220 C150,20 350,420 550,170 C700,0 780,160 820,100" fill="none" stroke="#fff" strokeWidth="2" />
          <path d="M-50,470 C150,270 350,670 550,420" fill="none" stroke="#fff" strokeWidth="1.5" />
          <circle cx="620" cy="120" r="210" fill="none" stroke="#fff" />
          <circle cx="90" cy="780" r="160" fill="none" stroke="#fff" />
        </svg>
        <div className="relative flex items-center gap-2.5">
          <span className="flex size-10 items-center justify-center rounded-lg bg-white/20 backdrop-blur">
            <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden="true">
              <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
            </svg>
          </span>
          <span className="text-lg font-bold">KidsCRM</span>
        </div>
        <div className="relative max-w-md">
          <h1 className="text-4xl font-bold leading-tight tracking-tight">Весь центр —<br />в одном месте</h1>
          <p className="mt-4 text-base text-white/85">Замените Excel и переписки в WhatsApp: дети, расписание и деньги под контролем.</p>
          <ul className="mt-8 space-y-3">
            {FEATURES.map(f => (
              <li key={f} className="flex items-center gap-3 text-[15px] font-medium">
                <span className="size-2 rounded-full bg-white" />
                {f}
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-white/70">© 2026 KidsCRM</p>
      </aside>

      <main className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="flex size-9 items-center justify-center rounded-md bg-gradient-to-br from-brand-400 to-brand-600 text-white">
              <svg viewBox="0 0 24 24" className="size-[18px]" fill="currentColor" aria-hidden="true">
                <path d="M12 2 2 7l10 5 10-5-10-5Zm-10 15 10 5 10-5M2 12l10 5 10-5" />
              </svg>
            </span>
            <span className="text-[17px] font-bold">KidsCRM</span>
          </div>
          <h2 className="text-2xl font-bold tracking-tight">Вход</h2>
          <p className="mt-1.5 text-sm text-ink-muted">Телефон и пароль сотрудника центра.</p>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4">
            <Field label="Телефон">
              {({ id }) => (
                <Input
                  id={id}
                  type="tel"
                  autoComplete="tel"
                  value={phone}
                  onChange={e => setPhone(e.target.value.replace(/[^\d+\s\-()]/g, ''))}
                  placeholder="+7 701 234 56 78"
                  required
                  autoFocus
                />
              )}
            </Field>
            <Field label="Пароль">
              {({ id }) => (
                <div className="relative">
                  <Input
                    id={id}
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    className="pr-10"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(v => !v)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-ink-subtle hover:text-ink"
                    aria-label={showPassword ? 'Скрыть пароль' : 'Показать пароль'}
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              )}
            </Field>
            {error && <p className="rounded-md bg-danger-50 px-3 py-2 text-sm text-danger-600" role="alert">{error}</p>}
            <Button type="submit" variant="primary" loading={loading} className="w-full justify-center">
              Войти {!loading && <ArrowRight className="size-4" />}
            </Button>
          </form>
          <p className="mt-6 text-center text-xs text-ink-subtle">Нет доступа — обратитесь к владельцу центра.</p>
        </div>
      </main>
    </div>
  )
}
