import { useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import { Button, Card, Field, Input } from '../ui'
import { t, useLang } from '../i18n'
import { formatPhone } from '../ui'
import { phoneDigits, phoneInputProps } from '../utils/formValidation'
import portal, { portalError } from './api'
import { useParent } from './useParent'
import { installPwa } from './pwa'

/*
 * Вход в кабинет: номер → код → кабинет (TRU-135). Паролей нет.
 * Ответ «код отправлен» одинаков для любого номера — экран не говорит,
 * есть ли номер в базе центра.
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
  const [step, setStep] = useState('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [wait, setWait] = useState(0)
  const codeInput = useRef(null)

  useEffect(() => { installPwa() }, [])
  useEffect(() => {
    if (wait <= 0) return undefined
    const timer = setTimeout(() => setWait(w => w - 1), 1000)
    return () => clearTimeout(timer)
  }, [wait])

  if (signedIn) return <Navigate to={location.state?.from || '/parent'} replace />

  async function sendCode(event) {
    event?.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await portal.post('auth/request-code/', { phone }, { anonymous: true })
      setPhone(data.phone)
      setWait(data.resend_in)
      setStep('code')
      setCode('')
      setTimeout(() => codeInput.current?.focus(), 50)
    } catch (err) {
      setError(portalError(err, ERRORS))
      const retry = Number(err.response?.headers?.['retry-after'])
      if (retry && step === 'code') setWait(retry)
    } finally {
      setBusy(false)
    }
  }

  async function verify(event) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const { data } = await portal.post('auth/verify/', { phone, code }, { anonymous: true })
      signIn(data.token)
      navigate(location.state?.from || '/parent', { replace: true })
    } catch (err) {
      setError(portalError(err, ERRORS))
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-canvas px-4 py-10">
      <div className="mb-6 flex flex-col items-center text-center">
        <img src="/parent/icon-192.png" alt="" className="mb-4 size-16 rounded-[18px] shadow-brand" />
        <h1 className="text-[22px] font-bold text-ink">{t('Кабинет родителя')}</h1>
        <p className="mt-1 max-w-xs text-sm text-ink-muted">{t('Расписание, посещения и абонемент ребёнка — в телефоне.')}</p>
      </div>

      <Card className="w-full max-w-sm">
        {location.state?.expired && step === 'phone' && !error && (
          <p className="mb-4 rounded-lg bg-surface-muted px-3 py-2 text-[13px] text-ink-muted">{t('Сессия закончилась — войдите заново.')}</p>
        )}

        {step === 'phone' ? (
          <form onSubmit={sendCode} className="space-y-4">
            <Field label={t('Номер телефона')} hint={t('Тот, что вы оставили в центре')} error={error}>
              {({ id, invalid }) => (
                <Input
                  id={id}
                  invalid={invalid}
                  value={phone}
                  onChange={e => setPhone(phoneDigits(e.target.value))}
                  placeholder="+7 701 123 45 67"
                  autoComplete="tel"
                  autoFocus
                  required
                  className="text-base"
                  {...phoneInputProps}
                />
              )}
            </Field>
            <Button type="submit" variant="primary" className="h-12 w-full text-base" loading={busy} icon={ArrowRight}>
              {t('Получить код')}
            </Button>
          </form>
        ) : (
          <form onSubmit={verify} className="space-y-4">
            <button type="button" onClick={() => { setStep('phone'); setError('') }} className="inline-flex items-center gap-1 text-[13px] font-semibold text-ink-muted hover:text-ink">
              <ArrowLeft className="size-4" /> {formatPhone(phone)}
            </button>
            <p className="text-sm text-ink-muted">{t('Если номер есть в базе центра, мы отправили на него код. Он придёт в Telegram или SMS.')}</p>
            <Field label={t('Код из сообщения')} error={error}>
              {({ id, invalid }) => (
                <Input
                  id={id}
                  ref={codeInput}
                  invalid={invalid}
                  value={code}
                  onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  placeholder="••••••"
                  required
                  className="text-center text-2xl font-bold tracking-[0.4em]"
                />
              )}
            </Field>
            <Button type="submit" variant="primary" className="h-12 w-full text-base" loading={busy} disabled={code.length !== 6}>
              {t('Войти')}
            </Button>
            <p className="text-center text-[13px] text-ink-muted">
              {wait > 0
                ? t('Новый код можно запросить через {n} с', { n: wait })
                : <button type="button" onClick={sendCode} disabled={busy} className="font-semibold text-brand-700 hover:underline">{t('Отправить код ещё раз')}</button>}
            </p>
          </form>
        )}
      </Card>

      <p className="mt-6 max-w-xs text-center text-[12px] text-ink-subtle">{t('Не приходит код или сменился номер — напишите администратору центра.')}</p>
    </div>
  )
}
