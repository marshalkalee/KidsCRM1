import { Ban, MessageCircle, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { MediaPreview } from '../components/files/ProtectedFile'
import ChatComposer from '../components/messaging/ChatComposer'
import { Button, EmptyState, Modal, Skeleton, apiErrorMessage, cn, formatDateTime, useToast } from '../ui'
import { t } from '../i18n'
import portal from './api'

/*
 * Чат с центром в кабинете — та же переписка, что WhatsApp: свои сообщения
 * справа, ответы центра слева. Написанное здесь центр видит в CRM (с
 * пометкой «из кабинета»), а отвечает обычно в WhatsApp — ответ виден и тут.
 */
export default function ChatWithCenter({ child, open, onClose }) {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [removing, setRemoving] = useState('')
  const list = useRef(null)
  const url = `children/${child.id}/chat/`

  const load = useCallback(() => portal.get(url).then(response => setData(response.data)).catch(() => {}), [url])

  // Пока окно открыто — новые ответы центра подтягиваются сами.
  useEffect(() => {
    if (!open) return undefined
    load()
    const timer = window.setInterval(load, 10000)
    return () => window.clearInterval(timer)
  }, [open, load])

  const count = data?.results.length || 0
  useEffect(() => {
    if (list.current) list.current.scrollTop = list.current.scrollHeight
  }, [count, open])

  async function remove(forEveryone) {
    setRemoving(forEveryone ? 'all' : 'me')
    try {
      const direction = deleting.direction === 'me' ? 'in' : 'out'
      const response = await portal.post(`${url}messages/${direction}/${deleting.id}/delete/`, { for_everyone: forEveryone })
      setData(response.data)
      setDeleting(null)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setRemoving('')
    }
  }

  // Из поля ввода: текст и/или файл (фото, документ, голосовое).
  async function send({ text, file }) {
    try {
      const body = new FormData()
      body.append('text', text)
      if (file) body.append('file', file)
      const response = await portal.post(url, body)
      setData(response.data)
    } catch (err) {
      toast.error(apiErrorMessage(err))
      throw err
    }
  }

  return (
    <Modal open={open} onClose={onClose} size="xl" title={data?.center || t('Чат с центром')}>
      <div className="-mx-1 space-y-3">
        {!data ? (
          <Skeleton className="h-48" />
        ) : data.results.length === 0 ? (
          <EmptyState icon={MessageCircle} title={t('Напишите центру')} description={t('Администратор ответит здесь и в WhatsApp.')} />
        ) : (
          <div ref={list} className="h-[60vh] space-y-2 overflow-y-auto rounded-xl bg-surface-muted p-4">
            {data.results.map(item => (
              <div key={`${item.direction}-${item.id}`} className={cn('flex', item.direction === 'me' ? 'justify-end' : 'justify-start')}>
                <div className={cn('max-w-[75%] rounded-xl px-3 py-2 shadow-card', item.direction === 'me' ? 'bg-success-50' : 'bg-surface')}>
                  {item.revoked ? (
                    <p className="flex items-center gap-1.5 text-sm italic text-ink-muted"><Ban className="size-4" />{t('Сообщение удалено')}</p>
                  ) : (
                    <>
                      {item.media && <div className={cn(item.text && 'mb-1.5')}><MediaPreview media={item.media} client={portal} /></div>}
                      {item.text && <p className="whitespace-pre-wrap break-words text-sm text-ink">{item.text}</p>}
                    </>
                  )}
                  <p className="mt-1 flex items-center justify-end gap-2 text-[11px] text-ink-muted">
                    <span>{formatDateTime(item.at)}</span>
                    {/* Видна всегда: в кабинет заходят с телефона, наведения там нет. */}
                    {!item.revoked && (
                      <button
                        type="button"
                        onClick={() => setDeleting(item)}
                        aria-label={t('Удалить сообщение')}
                        title={t('Удалить сообщение')}
                        className="-m-1 rounded p-1 text-ink-subtle hover:text-danger-600"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    )}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
        <ChatComposer onSend={send} placeholder={t('Сообщение центру…')} />
      </div>
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
            ? t('«У себя» — пропадёт только у вас. «У всех» — центр тоже увидит «Сообщение удалено».')
            : t('Сообщение пропадёт только у вас — у центра оно останется.')}
        </p>
      </Modal>
    </Modal>
  )
}
