import { useCallback, useEffect, useState } from 'react'
import { MessageCircle, MessagesSquare, Phone, StickyNote } from 'lucide-react'
import api from '../../api/axios'
import { Button, Card, EmptyState, ErrorState, Select, Skeleton, Textarea, apiErrorMessage, cn, formatDateTime, useToast } from '../../ui'

// Как CommunicationLog.Channel на бэке.
const CHANNELS = [
  { value: 'call', label: 'Звонок', icon: Phone, tone: 'bg-info-50 text-info-600' },
  { value: 'whatsapp', label: 'WhatsApp', icon: MessageCircle, tone: 'bg-success-50 text-success-600' },
  { value: 'comment', label: 'Комментарий', icon: StickyNote, tone: 'bg-warning-50 text-warning-600' },
]
const CHANNEL_BY_VALUE = Object.fromEntries(CHANNELS.map(c => [c.value, c]))

/**
 * Вкладка «Коммуникации»: быстрый ввод после звонка (канал, кому, заметка —
 * пара кликов, ТЗ п. 4.1) и лента записей. Лог append-only — записи не
 * правятся и не удаляются.
 */
export default function CommunicationsTab({ child, permissions, onCountChange }) {
  const [logs, setLogs] = useState(null)
  const [contacts, setContacts] = useState([])
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    api.get('clients/communications/', { params: { child: child.id } })
      .then(r => {
        setLogs(r.data.results || r.data)
        setError(false)
        onCountChange?.(r.data.count ?? (r.data.results || r.data).length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!permissions.can_log_communications) return
    api.get('clients/child-contacts/', { params: { child: child.id } })
      .then(r => setContacts(r.data.results || r.data))
      .catch(() => {})
  }, [child.id, permissions.can_log_communications])

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
      <div className="order-2 lg:order-1">
        {error && <Card><ErrorState onRetry={load} /></Card>}
        {!error && !logs && <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>}
        {!error && logs && logs.length === 0 && (
          <Card>
            <EmptyState icon={MessagesSquare} title="Записей пока нет" description="Здесь будет история звонков и переписки с семьёй." />
          </Card>
        )}
        {!error && logs && logs.length > 0 && (
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
                          {log.channel_label}
                          {log.parent_contact_full_name && <span className="font-normal text-ink-muted"> · {log.parent_contact_full_name}</span>}
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
        )}
      </div>
      {permissions.can_log_communications && (
        <div className="order-1 lg:sticky lg:top-24 lg:order-2">
          <QuickLogForm child={child} contacts={contacts} onCreated={load} />
        </div>
      )}
    </div>
  )
}

function QuickLogForm({ child, contacts, onCreated }) {
  const toast = useToast()
  const [channel, setChannel] = useState('call')
  const [contact, setContact] = useState('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api.post('clients/communications/', {
        child: child.id,
        channel,
        note,
        parent_contact: contact || null,
      })
      setNote('')
      toast.success('Запись добавлена')
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
        <p className="text-[15px] font-bold text-ink">Новая запись</p>
        <div className="grid grid-cols-3 gap-1.5" role="group" aria-label="Канал">
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
        {contacts.length > 0 && (
          <Select aria-label="С кем" value={contact} onChange={e => setContact(e.target.value)}>
            <option value="">Без контакта</option>
            {contacts.map(link => <option key={link.id} value={link.parent_contact}>{link.parent_contact_full_name}</option>)}
          </Select>
        )}
        <Textarea
          aria-label="Заметка"
          rows={3}
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="О чём договорились"
          onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e) }}
        />
        {error && <p className="text-sm text-danger-600">{error}</p>}
        <Button variant="primary" type="submit" loading={saving} disabled={!note.trim()}>Добавить</Button>
      </form>
    </Card>
  )
}
