import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Send } from 'lucide-react'
import api from '../../api/axios'
import { Badge, Card, Checkbox, Skeleton, apiErrorMessage, formatDateTime, useToast } from '../../ui'
import { t } from '../../i18n'
import { STATUS_TONE } from './status'

/**
 * Сообщения родителю в его карточке: согласие и последние отправки.
 * Сотрудник включает только служебные (по анкете или договору); отписку
 * родителя вернуть не может — это делает сам родитель.
 */
export default function ParentMessaging({ parentId }) {
  const toast = useToast()
  const [consent, setConsent] = useState(null)
  const [messages, setMessages] = useState(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    api.get(`messaging/parents/${parentId}/consent/`).then(res => setConsent(res.data)).catch(() => setConsent({}))
    api.get('messaging/messages/', { params: { parent: parentId } }).then(res => setMessages(res.data)).catch(() => setMessages({ results: [], total: 0 }))
  }, [parentId])
  useEffect(() => { load() }, [load])

  async function toggle(category, value) {
    setSaving(true)
    try {
      const res = await api.put(`messaging/parents/${parentId}/consent/`, { [category]: value })
      setConsent(res.data)
      toast.success(value ? t('Согласие отмечено') : t('Уведомления выключены'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (!consent || !messages) return <Skeleton className="h-40" />
  const utility = consent.utility
  const marketing = consent.marketing
  const selfOptOut = utility?.status === 'opted_out' && utility.source !== 'admin_form'

  return (
    <Card>
      <p className="flex items-center gap-2 text-[15px] font-bold text-ink"><Send className="size-4 text-ink-subtle" />{t('Сообщения родителю')}</p>
      <div className="mt-3 space-y-3">
        <div>
          <Checkbox
            checked={utility?.status === 'opted_in'}
            disabled={saving || selfOptOut}
            onChange={e => toggle('utility', e.target.checked)}
            label={<span className="text-sm text-ink">{t('Согласен на уведомления: абонемент, оплата, расписание')}</span>}
          />
          <p className="mt-1 pl-7 text-[12px] text-ink-muted">
            {selfOptOut
              ? t('Родитель отписался сам ({source}) — включить может только он.', { source: t(utility.source_label) })
              : utility
                ? `${t(utility.source_label)} · ${formatDateTime(utility.changed_at)}`
                : t('Отметьте, если родитель согласился в анкете или договоре.')}
          </p>
        </div>
        <div>
          <Checkbox
            checked={marketing?.status === 'opted_in'}
            disabled={saving || marketing?.status !== 'opted_in'}
            onChange={e => toggle('marketing', e.target.checked)}
            label={<span className="text-sm text-ink">{t('Акции и новости центра')}</span>}
          />
          <p className="mt-1 pl-7 text-[12px] text-ink-muted">{t('Даёт только сам родитель в кабинете. Выключить можно по его просьбе.')}</p>
        </div>
      </div>

      <div className="mt-4 border-t border-line pt-3">
        {messages.results.length === 0 ? (
          <p className="text-[13px] text-ink-muted">{t('Сообщений пока не было.')}</p>
        ) : (
          <ul className="space-y-2">
            {messages.results.slice(0, 5).map(m => (
              <li key={m.id} className="flex items-start justify-between gap-2 text-[13px]">
                <span className="min-w-0">
                  <span className="block font-semibold text-ink">{t(m.event_label)}</span>
                  <span className="text-ink-muted">{formatDateTime(m.sent_at || m.created_at)}{m.channel && ` · ${m.channel}`}</span>
                </span>
                <Badge tone={STATUS_TONE[m.status]}>{t(m.status_label)}</Badge>
              </li>
            ))}
          </ul>
        )}
        {messages.total > 0 && (
          <Link to={`/messaging?tab=journal&parent=${parentId}`} className="mt-3 inline-block text-[13px] font-semibold text-brand-600 hover:underline">
            {t('Весь журнал ({n})', { n: messages.total })}
          </Link>
        )}
      </div>
    </Card>
  )
}
