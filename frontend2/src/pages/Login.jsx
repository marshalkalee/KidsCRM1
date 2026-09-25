import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowRight, Eye, EyeOff } from 'lucide-react'
import AuthLayout from '../components/AuthLayout'
import { useSession } from '../session/SessionContext'
import { Button, Field, Input } from '../ui'

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
    <AuthLayout>
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
      <p className="mt-6 text-center text-sm text-ink-muted">
        Открываете свой центр? <Link to="/signup" className="font-semibold text-brand-700 hover:underline">Зарегистрироваться</Link>
      </p>
      <p className="mt-2 text-center text-xs text-ink-subtle">Сотрудникам доступ выдаёт владелец центра.</p>
    </AuthLayout>
  )
}
