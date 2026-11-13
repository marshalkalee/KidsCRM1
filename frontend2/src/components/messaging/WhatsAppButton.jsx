import { MessageCircle } from 'lucide-react'
import { useState } from 'react'
import api from '../../api/axios'
import { Button, Field, Modal, Textarea, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'
import { useCenterWhatsApp, waMeUrl } from './whatsappStatus'

/*
 * Кнопка «WhatsApp» по всей CRM. Если у центра подключён номер по QR-коду,
 * сотрудник правит готовый текст и отправляет его с номера центра — сообщение
 * попадает в журнал, историю заявки или ребёнка. Иначе — как раньше: свой
 * WhatsApp через wa.me с подставленным текстом.
 */

/**
 * phone — номер (для wa.me и поиска в CRM); parentId / leadId — кому именно;
 * childId — в чью карточку записать сообщение; text — готовый текст.
 */
export default function WhatsAppButton({ phone, text = '', parentId, leadId, childId, className, title, children, onSent }) {
  const status = useCenterWhatsApp()
  const [open, setOpen] = useState(false)
  const label = title || t('Написать в WhatsApp')

  if (!status?.can_send) {
    if (!phone) return null
    return (
      <a href={waMeUrl(phone, text)} target="_blank" rel="noreferrer" className={className} title={label} aria-label={label} onClick={() => onSent?.()}>
        {children}
      </a>
    )
  }
  if (!phone && !parentId && !leadId) return null
  return (
    <>
      <button type="button" className={className} title={label} aria-label={label} onClick={() => setOpen(true)}>
        {children}
      </button>
      {open && (
        <WhatsAppSendModal
          phone={phone}
          text={text}
          parentId={parentId}
          leadId={leadId}
          childId={childId}
          onClose={() => setOpen(false)}
          onSent={onSent}
        />
      )}
    </>
  )
}

function sendFromCenter({ phone, text, parentId, leadId, childId }) {
  return api.post('messaging/whatsapp/send/', {
    text,
    phone: phone || '',
    parent_id: parentId || null,
    lead_id: leadId || null,
    child_id: childId || null,
  })
}

/**
 * Для окон, где текст уже готов и виден (ИИ, напоминания пачкой): отправить
 * сразу с номера центра, без второго окна. children(mode) — подпись:
 * mode = 'center' (номер центра) или 'personal' (свой WhatsApp).
 */
export function WhatsAppQuickSend({ phone, text, parentId, leadId, childId, className, children, onSent }) {
  const status = useCenterWhatsApp()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const mode = status?.can_send ? 'center' : 'personal'
  const content = typeof children === 'function' ? children(mode) : children

  if (mode === 'personal') {
    if (!phone) return null
    return <a href={waMeUrl(phone, text)} target="_blank" rel="noreferrer" className={className} onClick={() => onSent?.()}>{content}</a>
  }
  async function send() {
    setBusy(true)
    try {
      await sendFromCenter({ phone, text, parentId, leadId, childId })
      toast.success(t('Сообщение отправляется с номера центра'))
      onSent?.()
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setBusy(false)
    }
  }
  return <button type="button" className={className} disabled={busy || !text?.trim()} onClick={send}>{content}</button>
}

function WhatsAppSendModal({ phone, text, parentId, leadId, childId, onClose, onSent }) {
  const toast = useToast()
  const [body, setBody] = useState(text)
  const [sending, setSending] = useState(false)

  async function send() {
    setSending(true)
    try {
      await sendFromCenter({ phone, text: body, parentId, leadId, childId })
      toast.success(t('Сообщение отправляется с номера центра'))
      onSent?.()
      onClose()
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setSending(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="md"
      title={t('Сообщение в WhatsApp')}
      description={t('Уйдёт с номера центра и сохранится в журнале рассылок.')}
      footer={(
        <>
          {phone && (
            <a href={waMeUrl(phone, body)} target="_blank" rel="noreferrer" className="mr-auto self-center text-[13px] font-semibold text-ink-muted hover:text-ink hover:underline">
              {t('Открыть в своём WhatsApp')}
            </a>
          )}
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" icon={MessageCircle} loading={sending} disabled={!body.trim()} onClick={send}>{t('Отправить')}</Button>
        </>
      )}
    >
      <Field label={t('Текст')}>
        {({ id }) => <Textarea id={id} rows={6} maxLength={4096} value={body} onChange={event => setBody(event.target.value)} autoFocus />}
      </Field>
    </Modal>
  )
}
