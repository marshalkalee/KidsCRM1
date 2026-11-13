import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MessageCircle, MessagesSquare, Paperclip, Phone, StickyNote, X } from 'lucide-react'
import api from '../../api/axios'
import { Button, Card, EmptyState, ErrorState, Select, Skeleton, Textarea, apiErrorMessage, cn, formatDateTime, useToast } from '../../ui'
import { t } from '../../i18n'
import { NoteHelper } from '../ai/assist'
import { useCenterWhatsApp } from '../messaging/whatsappStatus'
import { MediaPreview } from '../files/ProtectedFile'
import { ACCEPT_FILES, attachmentMedia } from '../files/fileHelpers'

// Как CommunicationLog.Channel на бэке.
const CHANNELS = [
  { value: 'call', get label() { return t('Звонок') }, icon: Phone, tone: 'bg-info-50 text-info-600' },
  { value: 'whatsapp', label: 'WhatsApp', icon: MessageCircle, tone: 'bg-success-50 text-success-600' },
  { value: 'comment', get label() { return t('Комментарий') }, icon: StickyNote, tone: 'bg-warning-50 text-warning-600' },
]
const CHANNEL_BY_VALUE = Object.fromEntries(CHANNELS.map(c => [c.value, c]))

/**
 * Коммуникации (ТЗ п. 4.1) — лента + быстрый ввод, общие для карточки
 * ребёнка (params {child}) и карточки родителя (params {family}: всё по
 * любому из его детей). Лог append-only — записи не правятся.
 *
 * childOptions — дети, о ком можно записать (одного не спрашиваем);
 * contactOptions — [{id, full_name}] для «с кем говорили»;
 * showChild — подписывать ребёнка в ленте (у родителя детей несколько);
 * stacked — форма над лентой (для узкой колонки, как в карточке родителя);
 * channels — какие каналы предлагать в форме (в карточке родителя WhatsApp
 * идёт чатом рядом, там — только звонок и комментарий);
 * emptyText — подпись пустой ленты.
 */
export function Communications({ params, canCreate, childOptions, contactOptions = [], fixedContact, showChild = false, stacked = false, channels, emptyText, onCountChange }) {
  const [logs, setLogs] = useState(null)
  const [error, setError] = useState(false)
  const query = JSON.stringify(params)

  const load = useCallback(() => {
    api.get('clients/communications/', { params: JSON.parse(query) })
      .then(r => {
        const rows = r.data.results || r.data
        setLogs(rows)
        setError(false)
        onCountChange?.(r.data.count ?? rows.length)
      })
      .catch(() => setError(true))
  }, [query, onCountChange])

  useEffect(() => { load() }, [load])

  return (
    <div className={cn('grid gap-4', !stacked && 'lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start')}>
      <div className={cn('order-2', !stacked && 'lg:order-1')}>
        {error && <Card><ErrorState onRetry={load} /></Card>}
        {!error && !logs && <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>}
        {!error && logs && logs.length === 0 && (
          <Card>
            <EmptyState icon={MessagesSquare} title={t('Записей пока нет')} description={emptyText || t('Здесь будет история звонков и переписки с семьёй.')} />
          </Card>
        )}
        {!error && logs && logs.length > 0 && <Feed logs={logs} showChild={showChild} />}
      </div>
      {canCreate && (childOptions.length > 0 || fixedContact) && (
        <div className={cn('order-1', !stacked && 'lg:sticky lg:top-24 lg:order-2')}>
          <QuickLogForm childOptions={childOptions} contactOptions={contactOptions} fixedContact={fixedContact} channels={channels} onCreated={load} />
        </div>
      )}
    </div>
  )
}

function Feed({ logs, showChild }) {
  return (
    <Card padded={false}>
      <ol className="divide-y divide-line">
        {logs.map(log => {
          const channel = CHANNEL_BY_VALUE[log.channel] || CHANNELS[2]
          const Icon = channel.icon
          return (
            <li key={log.id} className="flex gap-3 px-5 py-4">
              <span className={cn('flex size-9 shrink-0 items-center justify-center rounded-full', channel.tone)}>
                <Icon className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
                  <p className="text-sm font-semibold text-ink">
                    {t(log.channel_label)}
                    {log.incoming && <span className="font-normal text-success-600"> · {t('входящее')}</span>}
                    {log.parent_contact_full_name && <span className="font-normal text-ink-muted"> · {log.parent_contact_full_name}</span>}
                    {showChild && log.child && (
                      <>
                        <span className="font-normal text-ink-muted"> {t('· о')} </span>
                        <Link to={`/children/${log.child}`} className="font-normal text-brand-700 hover:underline">{log.child_name}</Link>
                      </>
                    )}
                  </p>
                  <time dateTime={log.created_at} className="text-xs text-ink-subtle">{formatDateTime(log.created_at)}</time>
                </div>
                <p className="mt-1 whitespace-pre-line text-sm text-ink">{log.note}</p>
                {log.attachments?.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {log.attachments.map(file => <MediaPreview key={file.id} media={attachmentMedia(`clients/communications/${log.id}/files/${file.id}/`, file)} />)}
                  </div>
                )}
                {log.author_name && <p className="mt-1 text-xs text-ink-subtle">{log.author_name}</p>}
              </div>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

const MAX_FILES = 5

function QuickLogForm({ childOptions, contactOptions, fixedContact, channels, onCreated }) {
  const toast = useToast()
  const whatsapp = useCenterWhatsApp()
  const [channel, setChannel] = useState('call')
  // В карточке родителя заметка по умолчанию — о семье, ребёнка можно выбрать.
  const [child, setChild] = useState(fixedContact ? '' : (childOptions[0]?.id || ''))
  const [contact, setContact] = useState(fixedContact || '')
  const [note, setNote] = useState('')
  const [files, setFiles] = useState([])
  const available = channels ? CHANNELS.filter(c => channels.includes(c.value)) : CHANNELS
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  // WhatsApp при подключённом номере центра — не заметка, а настоящее сообщение родителю.
  const sendsMessage = channel === 'whatsapp' && Boolean(whatsapp?.can_send) && Boolean(contact)

  async function submit(e) {
    e.preventDefault()
    if (!note.trim()) return
    setSaving(true)
    setError('')
    try {
      if (sendsMessage) {
        // Сообщение уходит родителю с номера центра; запись в ленте создаёт сервер.
        await api.post('messaging/whatsapp/send/', { parent_id: contact, child_id: child || null, text: note })
        toast.success(t('Сообщение отправляется с номера центра'))
      } else {
        // multipart: вместе с заметкой уходят файлы.
        const form = new FormData()
        form.append('channel', channel)
        form.append('note', note)
        if (child) form.append('child', child)
        if (contact) form.append('parent_contact', contact)
        files.forEach(file => form.append('files', file))
        await api.post('clients/communications/', form)
        toast.success(t('Запись добавлена'))
      }
      setNote('')
      setFiles([])
      onCreated()
    } catch (err) {
      const data = err.response?.data
      setError(data?.note?.[0] || data?.files?.[0] || data?.parent_contact?.[0] || data?.child?.[0] || apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <p className="text-[15px] font-bold text-ink">{t('Новая запись')}</p>
        <div className={cn('grid gap-1.5', available.length === 3 ? 'grid-cols-3' : 'grid-cols-2')} role="group" aria-label={t('Канал')}>
          {available.map(({ value, label, icon: Icon }) => (
            <button
              key={value}
              type="button"
              aria-pressed={channel === value}
              onClick={() => setChannel(value)}
              className={cn(
                'flex flex-col items-center gap-1 rounded-md border px-2 py-2 text-xs font-semibold transition-colors',
                channel === value ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line text-ink-muted hover:text-ink',
              )}
            >
              <Icon className="size-4" />
              {label}
            </button>
          ))}
        </div>
        {(fixedContact ? childOptions.length > 0 : childOptions.length > 1) && (
          <Select aria-label={t('О ком')} value={child} onChange={e => setChild(e.target.value)}>
            {fixedContact && <option value="">{t('Общая заметка')}</option>}
            {childOptions.map(option => <option key={option.id} value={option.id}>{option.full_name}</option>)}
          </Select>
        )}
        {!fixedContact && contactOptions.length > 0 && (
          <Select aria-label={t('С кем')} value={contact} onChange={e => setContact(e.target.value)}>
            <option value="">{t('Без контакта')}</option>
            {contactOptions.map(option => <option key={option.id} value={option.id}>{option.full_name}</option>)}
          </Select>
        )}
        <Textarea
          aria-label={t('Заметка')}
          rows={3}
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder={sendsMessage ? t('Текст сообщения родителю') : t('О чём договорились')}
          maxLength={2000}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e) }}
        />
        <NoteHelper text={note} onParsed={parsed => { setChannel(available.some(c => c.value === parsed.channel) ? parsed.channel : available[0].value); setNote(parsed.note) }} />
        {!sendsMessage && (
          <div className="flex flex-wrap items-center gap-1.5">
            {files.map((file, index) => (
              <span key={`${file.name}-${index}`} className="inline-flex max-w-full items-center gap-1 rounded-md bg-surface-muted px-2 py-1 text-xs text-ink">
                <Paperclip className="size-3.5 shrink-0" />
                <span className="truncate">{file.name}</span>
                <button type="button" aria-label={t('Убрать файл')} onClick={() => setFiles(list => list.filter((_, i) => i !== index))} className="text-ink-subtle hover:text-ink">
                  <X className="size-3.5" />
                </button>
              </span>
            ))}
            {files.length < MAX_FILES && (
              <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-ink-muted hover:bg-surface-muted hover:text-ink">
                <Paperclip className="size-3.5" />
                {t('Прикрепить файл')}
                <input
                  type="file"
                  multiple
                  accept={ACCEPT_FILES}
                  className="sr-only"
                  onChange={event => {
                    const picked = Array.from(event.target.files || [])
                    setFiles(list => [...list, ...picked].slice(0, MAX_FILES))
                    event.target.value = ''
                  }}
                />
              </label>
            )}
          </div>
        )}
        {error && <p className="text-sm text-danger-600">{error}</p>}
        <Button variant="primary" type="submit" loading={saving} disabled={!note.trim()}>{sendsMessage ? t('Отправить в WhatsApp') : t('Добавить')}</Button>
      </form>
    </Card>
  )
}
