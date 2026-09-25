import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MessageCircle, MessagesSquare, Phone, StickyNote } from 'lucide-react'
import api from '../../api/axios'
import { Button, Card, EmptyState, ErrorState, Select, Skeleton, Textarea, apiErrorMessage, cn, formatDateTime, useToast } from '../../ui'
import { t } from '../../i18n'

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
 * stacked — форма над лентой (для узкой колонки, как в карточке родителя).
 */
export function Communications({ params, canCreate, childOptions, contactOptions = [], fixedContact, showChild = false, stacked = false, onCountChange }) {
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
            <EmptyState icon={MessagesSquare} title={t('Записей пока нет')} description={t('Здесь будет история звонков и переписки с семьёй.')} />
          </Card>
        )}
        {!error && logs && logs.length > 0 && <Feed logs={logs} showChild={showChild} />}
      </div>
      {canCreate && childOptions.length > 0 && (
        <div className={cn('order-1', !stacked && 'lg:sticky lg:top-24 lg:order-2')}>
          <QuickLogForm childOptions={childOptions} contactOptions={contactOptions} fixedContact={fixedContact} onCreated={load} />
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
                    {log.parent_contact_full_name && <span className="font-normal text-ink-muted"> · {log.parent_contact_full_name}</span>}
                    {showChild && (
                      <>
                        <span className="font-normal text-ink-muted"> {t('· о')} </span>
                        <Link to={`/children/${log.child}`} className="font-normal text-brand-700 hover:underline">{log.child_name}</Link>
                      </>
                    )}
                  </p>
                  <time dateTime={log.created_at} className="text-xs text-ink-subtle">{formatDateTime(log.created_at)}</time>
                </div>
                <p className="mt-1 whitespace-pre-line text-sm text-ink">{log.note}</p>
                <p className="mt-1 text-xs text-ink-subtle">{log.author_name}</p>
              </div>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}

function QuickLogForm({ childOptions, contactOptions, fixedContact, onCreated }) {
  const toast = useToast()
  const [channel, setChannel] = useState('call')
  const [child, setChild] = useState(childOptions[0].id)
  const [contact, setContact] = useState(fixedContact || '')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!note.trim()) return
    setSaving(true)
    setError('')
    try {
      await api.post('clients/communications/', { child, channel, note, parent_contact: contact || null })
      setNote('')
      toast.success(t('Запись добавлена'))
      onCreated()
    } catch (err) {
      const data = err.response?.data
      setError(data?.note?.[0] || data?.parent_contact?.[0] || apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <p className="text-[15px] font-bold text-ink">{t('Новая запись')}</p>
        <div className="grid grid-cols-3 gap-1.5" role="group" aria-label={t('Канал')}>
          {CHANNELS.map(({ value, label, icon: Icon }) => (
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
        {childOptions.length > 1 && (
          <Select aria-label={t('О ком')} value={child} onChange={e => setChild(e.target.value)}>
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
          placeholder={t('О чём договорились')}
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e) }}
        />
        {error && <p className="text-sm text-danger-600">{error}</p>}
        <Button variant="primary" type="submit" loading={saving} disabled={!note.trim()}>{t('Добавить')}</Button>
      </form>
    </Card>
  )
}
