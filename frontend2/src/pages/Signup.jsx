import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowRight, Eye, EyeOff } from 'lucide-react'
import AuthLayout from '../components/AuthLayout'
import { useSession } from '../session/SessionContext'
import { Button, Field, Input } from '../ui'
import { t } from '../i18n'

/**
 * Регистрация центра (TRU-86): организация + владелец одним запросом
 * (/users/auth/register/ — тот же сериализатор, что у старого веба), сразу
 * вход и мастер настройки. slug организации придумывает сервер.
 */
export default function Signup() {
  const { status, reload } = useSession()
  const [form, setForm] = useState({ org_name: '', full_name: '', phone: '', password: '' })
  const [showPassword, setShowPassword] = useState(false)
  const [errors, setErrors] = useState({})
  const [loading, setLoading] = useState(false)
  const [registered, setRegistered] = useState(false)

  // Только что зарегистрировались — в мастер, а не на главную: сессия
  // становится ready раньше, чем срабатывает переход после запроса.
  if (status === 'ready') return <Navigate to={registered ? '/onboarding' : '/dashboard'} replace />

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  async function submit(e) {
    e.preventDefault()
    setLoading(true)
    setErrors({})
    try {
      const { data } = await axios.post('/api/v1/users/auth/register/', { ...form, phone: form.phone.trim() })
      localStorage.setItem('access', data.access)
      localStorage.setItem('refresh', data.refresh)
      setRegistered(true)
      await reload()
    } catch (err) {
      if (err.response?.status === 429) setErrors({ detail: t('Слишком много попыток. Подождите минуту.') })
      else if (err.response?.data && typeof err.response.data === 'object') setErrors(err.response.data)
      else setErrors({ detail: t('Нет связи с сервером.') })
    } finally {
      setLoading(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold tracking-tight">{t('Регистрация центра')}</h2>
      <p className="mt-1.5 text-sm text-ink-muted">{t('Пара минут — и можно заводить филиалы, группы и детей.')}</p>

      <form onSubmit={submit} className="mt-8 space-y-4">
        <Field label={t('Название центра')} error={errors.org_name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.org_name} onChange={e => set('org_name', e.target.value)} placeholder={t('Например, Студия «Грация»')} required autoFocus />}
        </Field>
        <Field label={t('Ваше имя')} error={errors.full_name}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} autoComplete="name" value={form.full_name} onChange={e => set('full_name', e.target.value)} required />}
        </Field>
        <Field label={t('Телефон')} hint={t('По нему вы будете входить')} error={errors.phone}>
          {({ id, invalid }) => (
            <Input
              id={id}
              invalid={invalid}
              type="tel"
              autoComplete="tel"
              value={form.phone}
              onChange={e => set('phone', e.target.value.replace(/[^\d+\s\-()]/g, ''))}
              placeholder="+7 701 234 56 78"
              required
            />
          )}
        </Field>
        <Field label={t('Пароль')} hint={t('Не короче 8 символов, не только цифры')} error={errors.password}>
          {({ id, invalid }) => (
            <div className="relative">
              <Input
                id={id}
                invalid={invalid}
                type={showPassword ? 'text' : 'password'}
                autoComplete="new-password"
                value={form.password}
                onChange={e => set('password', e.target.value)}
                className="pr-10"
                required
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1.5 text-ink-subtle hover:text-ink"
                aria-label={showPassword ? t('Скрыть пароль') : t('Показать пароль')}
              >
                {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          )}
        </Field>
        {errors.detail && <p className="rounded-md bg-danger-50 px-3 py-2 text-sm text-danger-600" role="alert">{errors.detail}</p>}
        <Button type="submit" variant="primary" loading={loading} className="w-full justify-center">
          {t('Создать центр')} {!loading && <ArrowRight className="size-4" />}
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-ink-muted">
        {t('Уже есть аккаунт?')} <Link to="/login" className="font-semibold text-brand-700 hover:underline">{t('Войти')}</Link>
      </p>
    </AuthLayout>
  )
}
