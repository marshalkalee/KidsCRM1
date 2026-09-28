import { useEffect, useState } from 'react'
import api from '../../api/axios'
import { Button, Field, Modal, Select, Textarea } from '../../ui'
import { t } from '../../i18n'
import { leadTitle } from './format'

/**
 * Перевод заявки в «Отказ» (TRU-94): причина из справочника обязательна,
 * комментарий — по желанию. «Отмена» — заявка остаётся где была.
 */
export default function RejectModal({ lead, onCancel, onConfirm }) {
  const [reasons, setReasons] = useState(null)
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.get('leads/rejection-reasons/', { params: { active: 1 } })
      .then(res => setReasons(res.data))
      .catch(() => setReasons([]))
  }, [])

  async function submit(e) {
    e.preventDefault()
    if (!reason) {
      setError(t('Укажите причину отказа.'))
      return
    }
    setSaving(true)
    try {
      await onConfirm({ rejection_reason: reason, comment })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onCancel}
      size="sm"
      title={t('Отказ')}
      description={t('Заявка: {name}', { name: leadTitle(lead) })}
      footer={
        <>
          <Button onClick={onCancel}>{t('Отмена')}</Button>
          <Button variant="danger" type="submit" form="reject-form" loading={saving}>{t('Перевести в отказ')}</Button>
        </>
      }
    >
      <form id="reject-form" onSubmit={submit} className="space-y-4">
        <Field label={t('Причина отказа')} required error={error}>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={reason} onChange={e => { setReason(e.target.value); setError(null) }}>
              <option value="">{reasons ? t('Выберите причину') : t('Загрузка…')}</option>
              {(reasons || []).map(r => <option key={r.id} value={r.id}>{t(r.name)}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Комментарий')}>
          {({ id }) => <Textarea id={id} value={comment} onChange={e => setComment(e.target.value)} placeholder={t('Необязательно: подробности для коллег')} />}
        </Field>
      </form>
    </Modal>
  )
}
