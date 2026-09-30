import { useState } from 'react'
import api from '../../api/axios'
import { Button, Field, Modal, Textarea, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'

export default function TrialCancelModal({ lead, onClose, onCancelled }) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(event) {
    event.preventDefault()
    if (!reason.trim()) return
    setSaving(true)
    try {
      const { data } = await api.post(`leads/${lead.id}/cancel-trial/`, { reason: reason.trim() })
      toast.success(t('Запись на пробное отменена'))
      onCancelled(data)
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Отмена записи на пробное')}
      description={t('Заявка вернётся в статус «Связались», а место на занятии освободится.')}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label={t('Причина отмены записи')} required>
          {({ id }) => (
            <Textarea
              id={id}
              autoFocus
              rows={4}
              value={reason}
              onChange={event => setReason(event.target.value)}
              placeholder={t('Например: заболели и пока не выбрали новую дату')}
              maxLength={500}
              required
            />
          )}
        </Field>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" onClick={onClose}>{t('Закрыть')}</Button>
          <Button type="submit" variant="danger" loading={saving} disabled={!reason.trim()}>
            {t('Отменить запись')}
          </Button>
        </div>
      </form>
    </Modal>
  )
}
