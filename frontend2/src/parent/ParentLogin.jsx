import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, LogIn } from 'lucide-react'
import { Button, Card, Field, Input } from '../ui'
import { t, useLang } from '../i18n'
import LanguageSwitcher from '../components/shell/LanguageSwitcher'
import logoMark from '../assets/logo-mark.png'
import { phoneDigits, phoneInputProps } from '../utils/formValidation'
import portal, { portalError } from './api'
import { useParent } from './useParent'
import { installPwa } from './pwa'

/*
 * Вход в кабинет: телефон + пароль (Д40). Пароль выдаёт администратор центра
 * в карточке родителя; родитель меняет его в профиле. Ошибка одна для любого
 * номера — экран не говорит, есть ли номер в базе центра.
 */

const ERRORS = {
  get offline() { return t('Нет связи. Проверьте интернет и попробуйте ещё раз.') },
  get other() { return t('Не получилось. Попробуйте ещё раз.') },
}

export default function ParentLogin() {
  useLang()
  const { signedIn, signIn } = useParent()
  const navigate = useNavigate()
  const location = useLocation()
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [shown, setShown] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { installPwa() }, [])

  if (signedIn) return <Navigate to={location.state?.from || '/parent'} replace />

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await portal.post('auth/login/', { phone, password }, { anonymous: true })
      signIn(data.token)
      navigate(location.state?.from || '/parent', { replace: true })
    } catch (err) {
      setError(portalError(err, ERRORS))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-dvh flex-col items-center justify-center bg-canvas px-4 py-20 sm:py-10">
      <div className="absolute right-4 top-4 z-20 sm:right-6 sm:top-6">
        <LanguageSwitcher />
      </div>
      <div className="mb-6 flex flex-col items-center text-center">
        <img src={logoMark} alt="" aria-hidden="true" className="mb-5 h-12 w-auto select-none" draggable={false} />
        <h1 className="text-[22px] font-bold text-ink">{t('Кабинет родителя')}</h1>
        <p className="mt-1 max-w-xs text-sm text-ink-muted">{t('Расписание, посещения и абонемент ребёнка — в телефоне.')}</p>
      </div>

      <Card className="w-full max-w-sm">
        {location.state?.expired && !error && (
          <p className="mb-4 rounded-lg bg-surface-muted px-3 py-2 text-[13px] text-ink-muted">{t('Сессия закончилась — войдите заново.')}</p>
        )}
        <form onSubmit={submit} className="space-y-4">
          <Field label={t('Номер телефона')} hint={t('Тот, что вы оставили в центре')}>
            {({ id }) => (
              <Input
                id={id}
                value={phone}
                onChange={e => setPhone(phoneDigits(e.target.value))}
                placeholder="+7 701 123 45 67"
                autoComplete="username"
                autoFocus
                required
                className="text-base"
                {...phoneInputProps}
              />
            )}
          </Field>
          <Field label={t('Пароль')} error={error}>
            {({ id, invalid }) => (
              <div className="relative">
                <Input
                  id={id}
                  invalid={invalid}
                  type={shown ? 'text' : 'password'}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  className="pr-11 text-base"
                />
                <button
                  type="button"
                  onClick={() => setShown(s => !s)}
                  aria-label={shown ? t('Скрыть пароль') : t('Показать пароль')}
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-ink-subtle hover:text-ink"
                >
                  {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            )}
          </Field>
          <Button type="submit" variant="primary" className="h-12 w-full text-base" loading={busy} icon={LogIn}>
            {t('Войти')}
          </Button>
          <p className="rounded-lg bg-surface-muted px-3 py-2.5 text-center text-[13px] leading-relaxed text-ink-muted">
            {t('Нет пароля или забыли? Попросите администратора центра — он выдаст новый.')}
          </p>
        </form>
      </Card>
    </div>
  )
}
