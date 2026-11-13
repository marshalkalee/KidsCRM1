import { Ban, MessageCircle, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import api from '../../api/axios'
import { Badge, Button, Card, EmptyState, Modal, Skeleton, apiErrorMessage, cn, formatDateTime, useToast } from '../../ui'
import { t } from '../../i18n'
import { MediaPreview } from '../files/ProtectedFile'
import { STATUS_TONE } from './status'
import ChatComposer from './ChatComposer'
import { useCenterWhatsApp } from './whatsappStatus'

/*
 * Переписка WhatsApp с родителем или заявкой — как чат: что написали нам,
 * что ответили сотрудники и что ушло автоматически. Ответ — с номера центра.
 */
export default function WhatsAppThread({ parentId, leadId }) {
  const toast = useToast()
  const status = useCenterWhatsApp()
  const [items, setItems] = useState(null)
  const [error, setError] = useState(false)
  const [deleting, setDeleting] = useState(null)
  const [removing, setRemoving] = useState('')
  const list = useRef(null)

  const load = useCallback(() => {
    const params = parentId ? { parent: parentId } : { lead: leadId }
    return api.get('messaging/whatsapp/thread/', { params })
      .then(response => { setItems(response.data.results); setError(false) })
      .catch(() => setError(true))
  }, [parentId, leadId])

  useEffect(() => {
    load()
    // Новые сообщения подтягиваются сами, пока карточка открыта.
    const timer = window.setInterval(load, 15000)
    return () => window.clearInterval(timer)
  }, [load])

  // Как в мессенджере: открыт конец переписки, без прокрутки всей страницы.
  const count = items?.length || 0
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [count])

  // Из поля ввода: текст и/или файл (голосовое — тоже файл).
  async function send({ text, file }) {
    try {
      const body = new FormData()
      body.append('text', text)
      if (parentId) body.append('parent_id', parentId)
      if (leadId) body.append('lead_id', leadId)
      if (file) body.append('file', file)
      await api.post('messaging/whatsapp/send/', body)
      await load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
      throw err
    }
  }

  async function remove(forEveryone) {
    setRemoving(forEveryone ? 'all' : 'me')
    try {
      await api.post(`messaging/whatsapp/messages/${deleting.direction}/${deleting.id}/delete/`, { for_everyone: forEveryone })
      setDeleting(null)
      await load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setRemoving('')
    }
  }

  if (error && !items) return null
  return (
    <Card padded={false}>
      <div className="flex items-center gap-2 border-b border-line px-5 py-3">
        <MessageCircle className="size-4 text-success-600" />
        <p className="text-[15px] font-bold text-ink">{t('Переписка в WhatsApp')}</p>
      </div>
      {!items ? (
        <Skeleton className="m-5 h-32" />
      ) : items.length === 0 ? (
        <EmptyState icon={MessageCircle} title={t('Переписки пока нет')} description={t('Сообщения в WhatsApp с номера центра появятся здесь.')} />
      ) : (
        <div ref={list} className="max-h-[28rem] space-y-2 overflow-y-auto bg-surface-muted px-4 py-4">
          {items.map(item => (
            <div key={`${item.direction}-${item.id}`} className={cn('flex', item.direction === 'out' ? 'justify-end' : 'justify-start')}>
              <div className={cn(
                'group relative max-w-[85%] rounded-xl px-3 py-2 shadow-card',
                item.direction === 'out' ? 'bg-success-50' : 'bg-surface',
              )}>
                {status?.can_send && (
                  <button
                    type="button"
                    onClick={() => setDeleting(item)}
                    aria-label={t('Удалить сообщение')}
                    title={t('Удалить сообщение')}
                    className={cn(
                      'absolute top-1/2 flex size-8 -translate-y-1/2 items-center justify-center rounded-full bg-surface text-ink-subtle opacity-0 shadow-card transition hover:text-danger-600 focus:opacity-100 group-hover:opacity-100',
                      item.direction === 'out' ? '-left-10' : '-right-10',
                    )}
                  >
                    <Trash2 className="size-4" />
                  </button>
                )}
                {item.revoked ? (
                  <p className="flex items-center gap-1.5 text-sm italic text-ink-muted">
                    <Ban className="size-4" />{t('Сообщение удалено')}
                  </p>
                ) : (
                  <>
                    {item.media && <div className={cn(item.text && 'mb-1.5')}><MediaPreview media={item.media} /></div>}
                    {item.text && <p className="whitespace-pre-wrap break-words text-sm text-ink">{item.text}</p>}
                  </>
                )}
                <p className="mt-1 flex flex-wrap items-center justify-end gap-x-2 gap-y-1 text-[11px] text-ink-muted">
                  {item.source === 'portal' && <span className="rounded bg-brand-50 px-1.5 py-0.5 font-semibold text-brand-700">{t('из кабинета')}</span>}
                  {item.author && <span>{t(item.author)}</span>}
                  <span>{formatDateTime(item.at)}</span>
                  {item.direction === 'out' && item.status && item.status !== 'sent' && (
                    <Badge tone={STATUS_TONE[item.status]}>{t(item.status_label)}</Badge>
                  )}
                </p>
                {item.error && <p className="mt-1 text-[11px] text-danger-600">{item.error}</p>}
              </div>
            </div>
          ))}
        </div>
      )}
      {status?.can_send && (
        <div className="border-t border-line px-4 py-3">
          <ChatComposer onSend={send} placeholder={t('Написать в WhatsApp…')} />
        </div>
      )}
      <Modal
        open={Boolean(deleting)}
        onClose={() => setDeleting(null)}
        size="sm"
        title={t('Удалить сообщение?')}
        footer={(
          <>
            <Button onClick={() => setDeleting(null)}>{t('Отмена')}</Button>
            <Button variant={deleting?.can_revoke ? 'secondary' : 'danger'} loading={removing === 'me'} onClick={() => remove(false)}>{t('Удалить у себя')}</Button>
            {deleting?.can_revoke && (
              <Button variant="danger" loading={removing === 'all'} onClick={() => remove(true)}>{t('Удалить у всех')}</Button>
            )}
          </>
        )}
      >
        <p className="text-sm text-ink-muted">
          {deleting?.can_revoke
            ? t('«У себя» — пропадёт только в CRM. «У всех» — удалится и в WhatsApp у собеседника.')
            : deleting?.direction === 'out'
              ? t('Сообщение пропадёт только в CRM. У всех WhatsApp даёт удалить лишь недавние доставленные сообщения.')
              : t('Сообщение пропадёт только в CRM — у собеседника его удалить нельзя.')}
        </p>
      </Modal>
    </Card>
  )
}
