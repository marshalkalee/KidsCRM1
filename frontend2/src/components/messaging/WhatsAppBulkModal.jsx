import { AlertTriangle, CheckCircle2, MessageCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import api from '../../api/axios'
import { Badge, Button, Modal, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'

export default function WhatsAppBulkModal({ open, onClose, source, ids, onSent }) {
  const toast = useToast()
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) {
      setPreview(null)
      return
    }
    setLoading(true)
    api.post('messaging/whatsapp/bulk/', { source, ids, preview: true })
      .then(response => setPreview(response.data))
      .catch(error => toast.error(apiErrorMessage(error)))
      .finally(() => setLoading(false))
  }, [open, source, ids, toast])

  async function send() {
    setLoading(true)
    try {
      const response = await api.post('messaging/whatsapp/bulk/', { source, ids, preview: false })
      toast.success(t('Поставлено в очередь: {n}', { n: response.data.queued }))
      onSent?.()
      onClose()
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('Напомнить в WhatsApp')}
      description={t('Перед отправкой проверяем согласие, номер и одобрение шаблона Meta.')}
      size="lg"
      footer={(
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" icon={MessageCircle} loading={loading} disabled={!preview?.ready} onClick={send}>
            {t('Отправить {n}', { n: preview?.ready || 0 })}
          </Button>
        </>
      )}
    >
      {loading && !preview ? (
        <p className="py-8 text-center text-sm text-ink-muted">{t('Проверяем получателей…')}</p>
      ) : preview && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-success-50 p-4">
              <p className="text-2xl font-bold text-success-600">{preview.ready}</p>
              <p className="text-xs text-ink-muted">{t('готовы к отправке')}</p>
            </div>
            <div className="rounded-lg bg-warning-50 p-4">
              <p className="text-2xl font-bold text-warning-600">{preview.total - preview.ready}</p>
              <p className="text-xs text-ink-muted">{t('нужно проверить')}</p>
            </div>
          </div>
          {!!preview.templates?.length && (
            <div className="rounded-lg border border-line bg-surface-muted p-4">
              <p className="mb-3 text-sm font-semibold text-ink">{t('Шаблоны отправки')}</p>
              <div className="space-y-3">
                {preview.templates.map(template => (
                  <div key={`${template.event}:${template.language}`}>
                    <p className="text-xs font-semibold text-ink">{template.name} · {template.language.toUpperCase()}</p>
                    <p className="mt-1 whitespace-pre-wrap text-xs text-ink-muted">{template.body}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
          <ul className="max-h-72 divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {preview.results.map(row => (
              <li key={row.subscription_id} className="flex items-start gap-3 px-4 py-3">
                {row.ready
                  ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-600" />
                  : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning-600" />}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{row.child}</p>
                  <p className="truncate text-xs text-ink-muted">{row.parent || t('Плательщик не указан')}</p>
                  {!row.ready && <p className="mt-1 text-xs text-warning-600">{t(row.reason)}</p>}
                </div>
                {row.ready && <Badge tone={row.service_window ? 'success' : 'neutral'}>{t(row.mode)}</Badge>}
              </li>
            ))}
          </ul>
          <p className="text-xs text-ink-muted">
            {t('Повторное такое же напоминание в тот же день не отправится. Ручная кнопка WhatsApp в строке остаётся доступной.')}
          </p>
        </div>
      )}
    </Modal>
  )
}
