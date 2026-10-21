import { useCallback, useEffect, useState } from 'react'
import { Bell, BellOff, Share, Smartphone } from 'lucide-react'
import { Badge, Button, Card, CardHeader, Checkbox, Skeleton, useToast } from '../ui'
import { t } from '../i18n'
import portal, { portalError } from './api'
import { currentSubscription, disablePush, dismiss, enablePush, permission, pushSupport, wasDismissed } from './push'

/*
 * Уведомления родителя (TRU-172): предложение на «Абонементе» — по месту, а
 * не при входе, — и настройки в профиле. Отправляет центр рассылок: push
 * первым, если не дошёл — WhatsApp или почта, без дублей.
 */

function useNotificationStatus() {
  const [status, setStatus] = useState(null)
  const [endpoint, setEndpoint] = useState('')
  const load = useCallback(() => currentSubscription()
    .then(subscription => {
      const current = subscription?.endpoint || ''
      setEndpoint(current)
      return portal.get('notifications/', { params: current ? { endpoint: current } : {} })
    })
    .then(res => setStatus(res.data))
    .catch(() => setStatus(false)), [])
  useEffect(() => { load() }, [load])
  return { status, setStatus, endpoint, reload: load }
}

/** Что нужно на iPhone: кабинет на экране «Домой», потом включить там. */
function IOSInstallHint() {
  return (
    <ol className="mt-2 list-decimal space-y-1 pl-5 text-[13px] text-ink-muted">
      <li>{t('Откройте кабинет в Safari и нажмите')} <Share className="inline size-3.5 align-[-2px]" /> {t('«Поделиться»')}.</li>
      <li>{t('Выберите «На экран „Домой“».')}</li>
      <li>{t('Откройте кабинет с иконки на экране и включите напоминания здесь.')}</li>
    </ol>
  )
}

/** Предложение на «Абонементе»: один раз, по делу; «Не сейчас» — молчим месяц. */
export function PushPrompt() {
  const toast = useToast()
  const { status, setStatus } = useNotificationStatus()
  const [hidden, setHidden] = useState(wasDismissed)
  const [busy, setBusy] = useState(false)
  const support = pushSupport()

  if (hidden || !status || !status.public_key || status.this_device) return null
  if (support === 'unsupported' || support === 'insecure' || permission() === 'denied') return null

  async function enable() {
    setBusy(true)
    try {
      setStatus(await enablePush(status.public_key))
      toast.success(t('Напоминания включены'))
    } catch (err) {
      toast.error(err.message === 'denied' ? t('Уведомления запрещены в браузере') : portalError(err, t('Не получилось включить напоминания')))
      setHidden(true)
    } finally {
      setBusy(false)
    }
  }

  function later() {
    dismiss()
    setHidden(true)
  }

  return (
    <Card>
      <div className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600"><Bell className="size-[18px]" /></span>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-bold text-ink">{t('Напоминать, когда занятия заканчиваются?')}</p>
          <p className="mt-0.5 text-[13px] text-ink-muted">{t('Пришлём уведомление, когда останется пара занятий, подойдёт оплата или отменят занятие. Без рекламы.')}</p>
          {support === 'ios-install' ? (
            <>
              <p className="mt-2 text-[13px] font-semibold text-ink">{t('На iPhone напоминания работают, если кабинет установлен на экран «Домой»:')}</p>
              <IOSInstallHint />
              <Button size="sm" variant="ghost" className="mt-2" onClick={later}>{t('Понятно')}</Button>
            </>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" variant="primary" icon={Bell} loading={busy} onClick={enable}>{t('Включить')}</Button>
              <Button size="sm" variant="ghost" onClick={later}>{t('Не сейчас')}</Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

/** Профиль: что получать, это устройство, отключить всё. */
export function NotificationSettings() {
  const toast = useToast()
  const { status, setStatus, endpoint, reload } = useNotificationStatus()
  const [busy, setBusy] = useState(false)
  const support = pushSupport()

  if (status === false) return null
  if (!status) return <Skeleton className="h-48" />

  async function run(action, done) {
    setBusy(true)
    try {
      const data = await action()
      if (data) setStatus(data)
      else await reload()
      if (done) toast.success(done)
    } catch (err) {
      toast.error(err.message === 'denied' ? t('Уведомления запрещены в браузере') : portalError(err, t('Не получилось сохранить')))
    } finally {
      setBusy(false)
    }
  }

  const patch = body => portal.patch('notifications/', { ...body, endpoint }).then(r => r.data)

  return (
    <Card>
      <CardHeader
        title={t('Уведомления')}
        description={t('Напоминания от центра: абонемент, оплата, отмена занятий, объявления. Рекламы нет.')}
        actions={status.enabled ? <Badge tone="success">{t('Включены')}</Badge> : <Badge>{t('Выключены')}</Badge>}
      />

      {status.public_key && (
        <div className="rounded-lg bg-surface-muted px-3 py-2.5">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink"><Smartphone className="size-4 text-ink-subtle" />{t('Это устройство')}</p>
          {status.this_device ? (
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[13px] text-ink-muted">{t('Напоминания приходят сюда.')}</p>
              <Button size="sm" variant="ghost" icon={BellOff} loading={busy} onClick={() => run(disablePush, t('Это устройство отключено'))}>{t('Не присылать сюда')}</Button>
            </div>
          ) : support === 'ios-install' ? (
            <IOSInstallHint />
          ) : support !== 'ok' ? (
            <p className="mt-1 text-[13px] text-ink-muted">{t('Этот браузер не умеет получать уведомления — откройте кабинет в Chrome или установите на телефон.')}</p>
          ) : permission() === 'denied' ? (
            <p className="mt-1 text-[13px] text-ink-muted">{t('Уведомления для кабинета запрещены в настройках браузера. Разрешите их для этого сайта и обновите страницу.')}</p>
          ) : (
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[13px] text-ink-muted">{t('Сюда напоминания не приходят.')}</p>
              <Button size="sm" variant="primary" icon={Bell} loading={busy} onClick={() => run(() => enablePush(status.public_key), t('Напоминания включены'))}>{t('Присылать сюда')}</Button>
            </div>
          )}
        </div>
      )}

      {status.enabled && (
        <ul className="mt-3 divide-y divide-line">
          {status.events.map(event => (
            <li key={event.key} className="py-2.5">
              <Checkbox
                checked={event.enabled}
                disabled={busy}
                onChange={e => run(() => patch({ events: { [event.key]: e.target.checked } }))}
                label={<span className="text-sm text-ink">{t(event.label)}</span>}
              />
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 border-t border-line pt-3">
        {status.enabled ? (
          <Button variant="ghost" icon={BellOff} loading={busy} onClick={() => run(() => patch({ enabled: false }), t('Все уведомления отключены'))}>{t('Отключить все уведомления')}</Button>
        ) : (
          <Button icon={Bell} loading={busy} onClick={() => run(() => patch({ enabled: true }), t('Уведомления включены'))}>{t('Получать уведомления от центра')}</Button>
        )}
      </div>
    </Card>
  )
}
