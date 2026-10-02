import { useEffect, useState } from 'react'
import { Copy, MessageCircle, RefreshCw, Sparkles, Wand2 } from 'lucide-react'
import api from '../../api/axios'
import { Button, Field, Modal, Select, Textarea, apiErrorMessage, cn, useToast } from '../../ui'
import { t } from '../../i18n'

/*
 * ИИ-помощник (эксперимент, ветка experiment/ai-assistant). Без ключа на
 * сервере кнопок нет — useAI().enabled === false.
 */

let statusPromise = null
function fetchStatus() {
  statusPromise ??= api.get('ai/status/').then(res => res.data).catch(() => ({ enabled: false }))
  return statusPromise
}

export function useAI() {
  // loading — пока статус не пришёл: экраны не мигают «без ИИ» → «с ИИ».
  const [status, setStatus] = useState({ enabled: false, loading: true })
  useEffect(() => {
    let alive = true
    fetchStatus().then(data => { if (alive) setStatus(data) })
    return () => { alive = false }
  }, [])
  return status
}

/** Метка «ИИ» — чтобы было видно, что текст придумала модель и его надо проверить. */
export function AIBadge({ className }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full bg-[linear-gradient(135deg,#ede9fe,#fce7f3)] px-2 py-0.5 text-[11px] font-bold text-[#7c3aed]', className)}>
      <Sparkles className="size-3" /> {t('ИИ')}
    </span>
  )
}

/**
 * «Вставить сообщение» в форме новой заявки: текст из WhatsApp или Instagram →
 * ИИ заполняет поля. Администратор всё видит и правит до сохранения.
 */
export function PasteMessage({ onParsed }) {
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  async function parse() {
    setBusy(true)
    try {
      const res = await api.post('ai/lead-from-text/', { text })
      onParsed(res.data)
      setOpen(false)
      setText('')
      toast.success(t('Поля заполнены — проверьте перед сохранением'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-lg border border-dashed border-[#c4b5fd] bg-[#faf5ff] px-3 py-2.5 text-left text-[13px] font-semibold text-[#7c3aed] hover:bg-[#f3e8ff]"
      >
        <Wand2 className="size-4 shrink-0" />
        {t('Вставить сообщение из WhatsApp или Instagram — ИИ заполнит поля')}
      </button>
    )
  }
  return (
    <div className="space-y-2 rounded-lg border border-[#ddd6fe] bg-[#faf5ff] p-3">
      <div className="flex items-center justify-between">
        <p className="text-[13px] font-semibold text-ink">{t('Сообщение родителя')}</p>
        <AIBadge />
      </div>
      <Textarea
        rows={4}
        autoFocus
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={t('Например: «Здравствуйте! Дочке 6 лет, хотим на балет. Айгерим, 8 707 111 22 33»')}
        aria-label={t('Сообщение родителя')}
      />
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>{t('Отмена')}</Button>
        <Button size="sm" variant="primary" icon={Sparkles} loading={busy} disabled={!text.trim()} onClick={parse}>{t('Заполнить')}</Button>
      </div>
    </div>
  )
}

const GOALS = [
  { value: 'first_contact', get label() { return t('Первое сообщение') } },
  { value: 'invite_trial', get label() { return t('Пригласить на пробное') } },
  { value: 'after_trial', get label() { return t('После пробного') } },
  { value: 'thinking', get label() { return t('Напомнить тем, кто думает') } },
  { value: 'renewal', get label() { return t('Предложить продление') } },
]

// Цель по статусу заявки — чтобы в обычном случае ничего не выбирать.
const GOAL_BY_STATUS = {
  new: 'first_contact',
  contacted: 'invite_trial',
  trial_scheduled: 'invite_trial',
  trial_attended: 'after_trial',
  thinking: 'thinking',
}

/**
 * «Написать с ИИ» в карточке заявки: сообщение родителю под статус, на
 * русском или казахском. Текст можно поправить, затем — WhatsApp или копировать.
 */
export function AIMessageModal({ lead, onClose }) {
  const toast = useToast()
  const [goal, setGoal] = useState(lead.kind === 'renewal' ? 'renewal' : GOAL_BY_STATUS[lead.status] || 'first_contact')
  const [language, setLanguage] = useState('ru')
  const [note, setNote] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)

  async function generate() {
    setBusy(true)
    try {
      const res = await api.post(`ai/leads/${lead.id}/message/`, { goal, language, note })
      setText(res.data.text)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('Скопировано'))
    } catch {
      toast.error(t('Не удалось скопировать'))
    }
  }

  const waUrl = `https://wa.me/${lead.phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`

  return (
    <Modal
      open
      onClose={onClose}
      title={<span className="flex items-center gap-2">{t('Сообщение родителю')} <AIBadge /></span>}
      description={t('ИИ составит текст по данным заявки. Проверьте его — отправляете вы.')}
      footer={
        text ? (
          <>
            <Button icon={Copy} onClick={copy}>{t('Копировать')}</Button>
            <a href={waUrl} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-2 rounded-md bg-success-600 px-4 text-sm font-semibold text-white hover:brightness-95">
              <MessageCircle className="size-4" /> {t('Открыть WhatsApp')}
            </a>
          </>
        ) : (
          <Button variant="primary" icon={Sparkles} loading={busy} onClick={generate}>{t('Составить')}</Button>
        )
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
          <Field label={t('Цель')}>
            {({ id }) => (
              <Select id={id} value={goal} onChange={e => setGoal(e.target.value)}>
                {GOALS.map(g => <option key={g.value} value={g.value}>{g.label}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Язык')}>
            {({ id }) => (
              <Select id={id} value={language} onChange={e => setLanguage(e.target.value)}>
                <option value="ru">Русский</option>
                <option value="kk">Қазақша</option>
              </Select>
            )}
          </Field>
        </div>
        <Field label={t('Пожелание (необязательно)')}>
          {({ id }) => <Textarea id={id} rows={2} value={note} onChange={e => setNote(e.target.value)} placeholder={t('Например: упомянуть, что в субботу есть место в группе 10:00')} />}
        </Field>
        {text && (
          <Field label={t('Текст')}>
            {({ id }) => <Textarea id={id} rows={6} value={text} onChange={e => setText(e.target.value)} />}
          </Field>
        )}
        {text && (
          <button type="button" onClick={generate} disabled={busy} className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#7c3aed] hover:underline disabled:opacity-50">
            <RefreshCw className={cn('size-3.5', busy && 'animate-spin')} /> {t('Другой вариант')}
          </button>
        )}
      </div>
    </Modal>
  )
}
