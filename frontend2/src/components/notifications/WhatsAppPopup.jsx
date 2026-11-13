import { MessageCircle, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '../../ui'
import { t } from '../../i18n'

/*
 * Всплывающее окно «Новое сообщение в WhatsApp» в углу любой страницы CRM.
 * Данные — из того же опроса уведомлений, что и колокольчик (раз в 10 с).
 * Показывается на новое сообщение, а не на каждую перезагрузку страницы:
 * время последнего закрытого окна помним в браузере. Вкладка свёрнута —
 * ещё и системное уведомление компьютера (если сотрудник разрешил).
 */

const DISMISSED_KEY = 'kc:whatsapp-popup-dismissed'

function readDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY) || ''
  } catch {
    return ''
  }
}

function isNewer(latest, dismissed) {
  return !dismissed || new Date(latest).getTime() > new Date(dismissed).getTime()
}

function canNotifySystem() {
  return typeof window !== 'undefined' && 'Notification' in window
}

export default function WhatsAppPopup({ items, onOpen }) {
  const navigate = useNavigate()
  const [dismissed, setDismissed] = useState(readDismissed)
  const [permission, setPermission] = useState(() => (canNotifySystem() ? Notification.permission : 'denied'))
  const notified = useRef('')

  const item = items?.find(entry => entry.kind === 'whatsapp_messages')
  const latest = item && item.count > 0 && item.unread ? item.latest_at : null
  const visible = Boolean(latest && isNewer(latest, dismissed))

  // Вкладка CRM не на экране — системное уведомление, один раз на сообщение.
  useEffect(() => {
    if (!visible || notified.current === latest) return
    notified.current = latest
    if (!canNotifySystem() || Notification.permission !== 'granted' || document.visibilityState === 'visible') return
    const note = new Notification(t('Новое сообщение в WhatsApp'), {
      body: `${item.name}: ${item.preview}`,
      tag: 'kc-whatsapp',
    })
    note.onclick = () => {
      window.focus()
      navigate(item.link)
      note.close()
    }
  }, [visible, latest, item, navigate])

  function dismiss() {
    setDismissed(latest)
    try { localStorage.setItem(DISMISSED_KEY, latest) } catch { /* окно просто покажется снова */ }
  }

  function open() {
    dismiss()
    onOpen?.('whatsapp_messages')
    navigate(item.link)
  }

  async function enableSystem() {
    try {
      setPermission(await Notification.requestPermission())
    } catch { /* браузер не дал спросить */ }
  }

  if (!visible) return null
  const others = item.count - 1
  return (
    <div
      role="alert"
      className="fixed bottom-4 right-4 z-50 w-[calc(100%-2rem)] max-w-sm rounded-xl border border-success-600/30 bg-surface p-4 shadow-pop sm:bottom-6 sm:right-6"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-success-50 text-success-600">
          <MessageCircle className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-semibold text-success-600">{t('Новое сообщение в WhatsApp')}</p>
          <p className="mt-0.5 truncate text-sm font-bold text-ink">{item.name}</p>
          <p className="mt-0.5 line-clamp-2 break-words text-sm text-ink-muted">{item.preview}</p>
          {others > 0 && <p className="mt-1 text-xs text-ink-subtle">{t('Ещё ждут ответа: {n}', { n: others })}</p>}
        </div>
        <button type="button" onClick={dismiss} aria-label={t('Закрыть')} className="-mr-1 -mt-1 rounded-md p-1 text-ink-subtle hover:bg-surface-muted hover:text-ink">
          <X className="size-4" />
        </button>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        {canNotifySystem() && permission === 'default' ? (
          <button type="button" onClick={enableSystem} className="text-left text-xs font-semibold text-ink-muted hover:text-ink hover:underline">
            {t('Уведомлять, даже когда CRM свёрнута')}
          </button>
        ) : <span />}
        <Button size="sm" variant="primary" icon={MessageCircle} onClick={open}>{t('Открыть')}</Button>
      </div>
    </div>
  )
}
