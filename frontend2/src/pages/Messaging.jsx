import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowDown, ArrowUp, Camera, CheckCircle2, ChevronDown, Mail, MessageCircle, Moon, Phone,
  PhoneIncoming, Play, RefreshCw, Send, Undo2, X,
} from 'lucide-react'
import api from '../api/axios'
import { STATUS_TONE } from '../components/messaging/status'
import {
  Badge, Button, Card, CardHeader, Checkbox, Dropdown, EmptyState, ErrorState, Field, Input, PageHeader,
  Select, Skeleton, Textarea, apiErrorMessage, cn, formatDateTime, useToast,
} from '../ui'
import { t } from '../i18n'

/*
 * Рассылки родителям (TRU-168): журнал — что и кому ушло; тексты писем
 * центра на ru и kk; тихие часы и порядок каналов. Отправляет система
 * (события — TRU-171), здесь — посмотреть и настроить.
 */

// Почему не ушло — и что сделать (для статусов без текста ошибки).
const STATUS_HINT = {
  no_consent: () => t('Родитель не давал согласия на уведомления. Если согласился в анкете или договоре — отметьте в его карточке.'),
  opted_out: () => t('Родитель отписался. Снова включить может только он сам.'),
  queued: () => t('Ждёт отправки — обычно это секунды.'),
}

const LANGS = [
  { key: 'ru', label: 'Русский' },
  { key: 'kk', label: 'Қазақша' },
]

export function TelephonyCalls() {
  const toast = useToast()
  const [calls, setCalls] = useState(null)
  const [connection, setConnection] = useState(null)
  const [connectionForm, setConnectionForm] = useState(null)
  const [savingConnection, setSavingConnection] = useState(false)
  const [error, setError] = useState(false)
  const load = useCallback(() => Promise.all([
    api.get('messaging/telephony/calls/'),
    api.get('messaging/telephony/').catch(() => ({ data: null })),
  ]).then(([callsResponse, connectionResponse]) => {
    setCalls(callsResponse.data)
    setConnection(connectionResponse.data)
    if (connectionResponse.data) {
      setConnectionForm(current => current || {
        provider: connectionResponse.data.provider,
        virtual_number: connectionResponse.data.virtual_number || '',
        api_key: '',
        api_secret: '',
        recording_enabled: connectionResponse.data.recording_enabled,
        recording_notice_confirmed: connectionResponse.data.recording_notice_confirmed,
      })
    }
    setError(false)
  }).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  async function promote(call) {
    try {
      const { data } = await api.post(`messaging/telephony/calls/${call.id}/promote/`)
      toast.success(t('Заявка создана'))
      window.location.assign(`/leads/${data.lead_id}`)
    } catch (requestError) { toast.error(apiErrorMessage(requestError)) }
  }

  async function play(call) {
    try {
      const { data } = await api.get(`messaging/telephony/calls/${call.id}/recording/`)
      window.open(data.url, '_blank', 'noopener,noreferrer')
    } catch (requestError) { toast.error(apiErrorMessage(requestError)) }
  }

  async function saveConnection() {
    setSavingConnection(true)
    try {
      const { data } = await api.put('messaging/telephony/', connectionForm)
      setConnection(data)
      setConnectionForm({ ...connectionForm, api_key: '', api_secret: '' })
      toast.success(t('Настройки телефонии сохранены'))
    } catch (requestError) { toast.error(apiErrorMessage(requestError)) }
    finally { setSavingConnection(false) }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!calls) return <Skeleton className="h-80" />
  return (
    <div>
      <PageHeader description={t('Входящие, исходящие и пропущенные звонки. Если АТС недоступна, CRM откроет номер в телефоне.')} />
      {connection && (
        <Card className="mb-4">
          <CardHeader
            title={t('Телефония')}
            description={connection.provider === 'console'
              ? t('Тестовый режим: звонок открывается через телефон устройства.')
              : t('Подключение Zadarma для виртуального номера Казахстана.')}
            actions={<Badge tone={connection.status === 'connected' ? 'success' : 'neutral'} dot>{t(connection.status === 'connected' ? 'Подключена' : 'Не подключена')}</Badge>}
          />
        </Card>
      )}
      {connectionForm && (
        <Card className="mb-4">
          <CardHeader title={t('Настройки АТС')} description={t('Ключи доступны только владельцу и никогда не возвращаются из API.')} />
          <div className="grid gap-4 md:grid-cols-2">
            <Field label={t('Провайдер')}>
              {({ id }) => (
                <Select id={id} value={connectionForm.provider} onChange={event => setConnectionForm({ ...connectionForm, provider: event.target.value })}>
                  <option value="console">{t('Тестовый режим')}</option>
                  <option value="zadarma">Zadarma</option>
                </Select>
              )}
            </Field>
            <Field label={t('Виртуальный номер')}>
              {({ id }) => <Input id={id} value={connectionForm.virtual_number} onChange={event => setConnectionForm({ ...connectionForm, virtual_number: event.target.value })} placeholder="+7 700 000 00 00" />}
            </Field>
            <Field label={t('API-ключ')}>
              {({ id }) => <Input id={id} value={connectionForm.api_key} onChange={event => setConnectionForm({ ...connectionForm, api_key: event.target.value })} placeholder={connection.has_api_key ? t('Ключ уже сохранён') : ''} />}
            </Field>
            <Field label={t('API-секрет')}>
              {({ id }) => <Input id={id} type="password" value={connectionForm.api_secret} onChange={event => setConnectionForm({ ...connectionForm, api_secret: event.target.value })} placeholder={connection.has_api_key ? t('Секрет уже сохранён') : ''} />}
            </Field>
          </div>
          <div className="mt-4 grid gap-3">
            <Checkbox checked={connectionForm.recording_enabled} onChange={event => setConnectionForm({ ...connectionForm, recording_enabled: event.target.checked })} label={t('Хранить ссылки на записи разговоров')} />
            {connectionForm.recording_enabled && <Checkbox checked={connectionForm.recording_notice_confirmed} onChange={event => setConnectionForm({ ...connectionForm, recording_notice_confirmed: event.target.checked })} label={t('Подтверждаю, что звонящий предупреждается о записи разговора')} />}
          </div>
          <Button className="mt-5" variant="primary" loading={savingConnection} onClick={saveConnection}>{t('Сохранить настройки')}</Button>
        </Card>
      )}
      <Card>
        <CardHeader title={t('Журнал звонков')} description={t('Карточка клиента открывается по известному номеру. Пропущенные звонки создают задачу перезвонить.')} />
        {!calls.length ? <EmptyState icon={Phone} title={t('Звонков пока нет')} description={t('После подключения АТС входящие и исходящие появятся здесь.')} /> : (
          <div className="divide-y divide-line">
            {calls.map(call => {
              const targetUrl = call.target?.type === 'child' ? `/children/${call.target.id}` : call.target?.type === 'parent' ? `/parents/${call.target.id}` : call.target?.type === 'lead' ? `/leads/${call.target.id}` : ''
              return (
                <div key={call.id} className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center">
                  <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600"><PhoneIncoming className="size-5" /></span>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-ink">{call.target?.name || t('Неизвестный номер')}</p>
                    <p className="text-sm text-ink-muted">{call.phone} · {t(call.direction === 'inbound' ? 'Входящий' : 'Исходящий')} · {t(call.status === 'missed' ? 'Пропущен' : call.status === 'completed' ? 'Завершён' : call.status === 'external' ? 'Передан на устройство' : call.status === 'failed' ? 'Ошибка' : 'Звонит')}</p>
                    <p className="text-xs text-ink-subtle">{formatDateTime(call.started_at)} · {call.duration_seconds} {t('сек.')}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {targetUrl && <Button to={targetUrl}>{t('Открыть карточку')}</Button>}
                    {!call.target && <Button onClick={() => promote(call)}>{t('Создать заявку')}</Button>}
                    {call.has_recording && <Button icon={Play} onClick={() => play(call)}>{t('Слушать запись')}</Button>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}

export function MessagingJournal() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [open, setOpen] = useState(null)
  const [reply, setReply] = useState('')
  const [sendingReply, setSendingReply] = useState(false)
  const filters = { parent: params.get('parent') || '', status: params.get('status') || '', event: params.get('event') || '' }

  const load = useCallback(() => {
    const query = Object.fromEntries(Object.entries({ parent: params.get('parent'), status: params.get('status'), event: params.get('event') }).filter(([, v]) => v))
    api.get('messaging/messages/', { params: query }).then(res => { setData(res.data); setError(false) }).catch(() => setError(true))
  }, [params])
  useEffect(() => { load() }, [load])

  function setFilter(key, value) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
  }

  async function sendReply() {
    setSendingReply(true)
    try {
      await api.post('messaging/whatsapp/reply/', {
        parent_id: data.whatsapp_reply.parent_id,
        body: reply,
      })
      setReply('')
      toast.success(t('Ответ поставлен в очередь'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSendingReply(false)
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!data) return <Skeleton className="h-96" />

  const parentName = filters.parent && data.results[0]?.parent.name

  return (
    <div>
      <PageHeader description={t('Что система написала родителям: когда, каким каналом, что вышло. Отписка и отказы — здесь же.')} />
      {filters.parent && data.whatsapp_reply && (
        <Card className="mt-4">
          <CardHeader
            title={t('Свободный ответ в WhatsApp')}
            description={data.whatsapp_reply.available
              ? t('Родитель написал менее 24 часов назад — можно ответить обычным текстом.')
              : t(data.whatsapp_reply.reason)}
          />
          {data.whatsapp_reply.available ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field className="min-w-0 flex-1" label={t('Текст ответа')}>
                {({ id }) => (
                  <Textarea id={id} rows={3} maxLength={4096} value={reply} onChange={event => setReply(event.target.value)} />
                )}
              </Field>
              <Button variant="primary" icon={MessageCircle} loading={sendingReply} disabled={!reply.trim()} onClick={sendReply}>
                {t('Отправить')}
              </Button>
            </div>
          ) : (
            <p className="text-sm text-ink-muted">{t('Свободный ответ сейчас недоступен. Для нового диалога используйте одобренный шаблон Meta.')}</p>
          )}
        </Card>
      )}
      <Card padded={false} className="mt-4">
        {/* Шапка списка: сколько сообщений и фильтры — в одной строке. */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
          <p className="mr-auto text-[15px] font-bold text-ink">
            {t('Сообщения')} <span className="ml-1 text-[13px] font-semibold text-ink-subtle">{data.total}</span>
          </p>
          {filters.parent && (
            <button
              type="button"
              onClick={() => setFilter('parent', '')}
              className="inline-flex h-9 items-center gap-1.5 rounded-md bg-brand-50 px-3 text-xs font-semibold text-brand-600 hover:bg-brand-100"
            >
              {parentName ? t('Родитель: {name}', { name: parentName }) : t('Один родитель')}
              <X className="size-3.5" />
            </button>
          )}
          <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto">
          <div className="min-w-0 sm:w-52">
            <Dropdown
              size="sm"
              ariaLabel={t('Событие')}
              value={filters.event}
              onChange={v => setFilter('event', v)}
              options={[{ value: '', label: t('Все события') }, ...data.events.map(e => ({ value: e.key, label: t(e.label) }))]}
            />
          </div>
          <div className="min-w-0 sm:w-44">
            <Dropdown
              size="sm"
              ariaLabel={t('Статус')}
              value={filters.status}
              onChange={v => setFilter('status', v)}
              options={[{ value: '', label: t('Все статусы') }, ...data.statuses.map(st => ({ value: st.key, label: t(st.label) }))]}
            />
          </div>
          </div>
        </div>
        {data.results.length === 0 ? (
          <EmptyState icon={Send} title={t('Сообщений пока нет')} description={t('Когда система напишет родителю, здесь будет видно, что ушло.')} />
        ) : (
          <ul className="divide-y divide-line">
            {data.results.map(m => (
              <li key={m.id}>
                <button type="button" onClick={() => setOpen(open === m.id ? null : m.id)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 text-left">
                  <span className="min-w-[10rem] flex-1">
                    <span className="block text-sm font-semibold text-ink">{m.parent.name}</span>
                    <span className="text-[13px] text-ink-muted">{t(m.event_label)} · {formatDateTime(m.sent_at || m.created_at)}{m.channel && ` · ${m.channel}`}</span>
                  </span>
                  <Badge tone={STATUS_TONE[m.status]}>{t(m.status_label)}</Badge>
                  <ChevronDown className={cn('size-4 text-ink-subtle transition-transform', open === m.id && 'rotate-180')} />
                </button>
                {open === m.id && (
                  <div className="space-y-2 bg-surface-muted px-5 py-3 text-[13px]">
                    {m.recipient && <p className="text-ink-muted">{t('Кому')}: <span className="text-ink">{m.recipient}</span></p>}
                    {m.scheduled_for && m.status === 'deferred' && <p className="text-ink-muted">{t('Уйдёт после тихих часов: {when}', { when: formatDateTime(m.scheduled_for) })}</p>}
                    {m.error && <p className="text-danger-600">{m.error}</p>}
                    {!m.error && STATUS_HINT[m.status] && <p className="text-ink-muted">{STATUS_HINT[m.status]()}</p>}
                    {m.subject && <p className="font-semibold text-ink">{m.subject}</p>}
                    {m.body && <pre className="whitespace-pre-wrap font-sans text-ink">{m.body}</pre>}
                    <Link to={`/parents/${m.parent.id}`} className="inline-block font-semibold text-brand-600 hover:underline">{t('Карточка родителя')}</Link>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {data.total > data.results.length && (
        <p className="mt-2 text-[13px] text-ink-muted">{t('Показаны последние {n} из {total} — сузьте фильтром.', { n: data.results.length, total: data.total })}</p>
      )}
    </div>
  )
}

export function MessagingInbox() {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [status, setStatus] = useState('')
  const [resolving, setResolving] = useState('')

  const load = useCallback((quiet = false) => {
    api.get('messaging/whatsapp/inbox/', { params: status ? { status } : {} })
      .then(response => { setData(response.data); setError(false) })
      .catch(() => { if (!quiet) setError(true) })
  }, [status])

  useEffect(() => {
    load()
    const timer = window.setInterval(() => load(true), 15000)
    return () => window.clearInterval(timer)
  }, [load])

  async function bind(message, candidate) {
    setResolving(message.id)
    try {
      await api.post(`messaging/whatsapp/inbox/${message.id}/resolve/`, {
        [`${candidate.type}_id`]: candidate.id,
      })
      toast.success(t('Сообщение привязано'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setResolving('')
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!data) return <Skeleton className="h-96" />

  return (
    <div>
      <PageHeader description={t('Входящие сообщения автоматически попадают в историю ребёнка или заявки. Неоднозначные совпадения остаются здесь для ручной привязки.')} />
      <Card padded={false} className="mt-4">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <div className="mr-auto">
            <p className="font-bold text-ink">{t('Входящие WhatsApp')}</p>
            <p className="text-[13px] text-ink-muted">{t('Нужно разобрать: {n}', { n: data.unresolved })}</p>
          </div>
          <div className="w-52">
            <Dropdown
              size="sm"
              ariaLabel={t('Статус')}
              value={status}
              onChange={setStatus}
              options={[
                { value: '', label: t('Все статусы') },
                ...data.statuses.map(item => ({ value: item.key, label: t(item.label) })),
              ]}
            />
          </div>
          <Button variant="secondary" icon={RefreshCw} onClick={() => load()}>{t('Обновить')}</Button>
        </div>
        {data.results.length === 0 ? (
          <EmptyState
            icon={MessageCircle}
            title={t('Входящих сообщений пока нет')}
            description={t('После подключения Meta Cloud API сообщения родителей появятся здесь автоматически.')}
          />
        ) : (
          <ul className="divide-y divide-line">
            {data.results.map(message => (
              <li key={message.id} className="space-y-3 px-5 py-4">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-ink">{message.phone}</p>
                      <Badge tone={message.status === 'unresolved' ? 'warning' : message.status === 'failed' ? 'danger' : 'success'}>
                        {t(message.status_label)}
                      </Badge>
                      {message.reply_window_open && <Badge tone="info">{t('Можно ответить в течение 24 часов')}</Badge>}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{message.text || `[${message.type}]`}</p>
                    <p className="mt-1 text-xs text-ink-muted">{formatDateTime(message.provider_sent_at || message.created_at)}</p>
                  </div>
                  {message.child && <Link className="text-sm font-semibold text-brand-600 hover:underline" to={`/children/${message.child.id}`}>{message.child.name}</Link>}
                  {message.lead && <Link className="text-sm font-semibold text-brand-600 hover:underline" to={`/leads/${message.lead.id}`}>{message.lead.name}</Link>}
                </div>
                {Object.keys(message.media || {}).length > 0 && (
                  <div className="rounded-lg bg-surface-muted px-3 py-2 text-xs text-ink-muted">
                    {t('Вложение')}: {message.media.filename || message.media.mime_type || message.type}
                  </div>
                )}
                {message.resolution_note && <p className="text-[13px] text-ink-muted">{message.resolution_note}</p>}
                {message.status === 'unresolved' && (
                  <div className="rounded-xl border border-warning-200 bg-warning-50 p-3">
                    <p className="mb-2 text-xs font-bold uppercase tracking-wide text-warning-800">{t('Выберите карточку вручную')}</p>
                    {message.candidates.length ? (
                      <div className="flex flex-wrap gap-2">
                        {message.candidates.map(candidate => (
                          <Button
                            key={`${candidate.type}-${candidate.id}`}
                            variant="secondary"
                            loading={resolving === message.id}
                            onClick={() => bind(message, candidate)}
                          >
                            {candidate.type === 'child' ? t('Ребёнок') : t('Заявка')}: {candidate.name}
                          </Button>
                        ))}
                      </div>
                    ) : <p className="text-sm text-warning-800">{t('Подходящих карточек не найдено')}</p>}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

export function InstagramInbox() {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [status, setStatus] = useState('')
  const [reply, setReply] = useState({})
  const [busy, setBusy] = useState('')
  const load = useCallback((quiet = false) => {
    api.get('messaging/instagram/inbox/', { params: status ? { status } : {} })
      .then(response => { setData(response.data); setError(false) })
      .catch(() => { if (!quiet) setError(true) })
  }, [status])

  useEffect(() => {
    load()
    const timer = window.setInterval(() => load(true), 15000)
    return () => window.clearInterval(timer)
  }, [load])

  async function action(message, name, request) {
    setBusy(`${name}-${message.id}`)
    try {
      await request()
      toast.success(name === 'reply' ? t('Ответ отправлен') : t('Заявка создана'))
      setReply(current => ({ ...current, [message.id]: '' }))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy('')
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!data) return <Skeleton className="h-96" />
  return (
    <div>
      <PageHeader description={t('Direct и вопросы из комментариев попадают в воронку. Реакции и отметки друзей остаются вне заявок.')} />
      <Card padded={false} className="mt-4">
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-4">
          <div className="mr-auto">
            <p className="font-bold text-ink">{t('Входящие Instagram')}</p>
            <p className="text-[13px] text-ink-muted">{t('Нужно разобрать: {n}', { n: data.unresolved })}</p>
          </div>
          <div className="w-52">
            <Dropdown
              size="sm"
              ariaLabel={t('Статус')}
              value={status}
              onChange={setStatus}
              options={[{ value: '', label: t('Все статусы') }, ...data.statuses.map(item => ({ value: item.key, label: t(item.label) }))]}
            />
          </div>
          <Button variant="secondary" icon={RefreshCw} onClick={() => load()}>{t('Обновить')}</Button>
        </div>
        {data.results.length === 0 ? (
          <EmptyState icon={Camera} title={t('Входящих Instagram пока нет')} description={t('После подключения Instagram Business сообщения и комментарии появятся здесь автоматически.')} />
        ) : (
          <ul className="divide-y divide-line">
            {data.results.map(message => (
              <li key={message.id} className="space-y-3 px-5 py-4">
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-ink">{message.sender_name ? `@${message.sender_name}` : message.sender_id}</p>
                      <Badge tone={message.kind === 'comment' ? 'warning' : 'info'}>{t(message.kind_label)}</Badge>
                      <Badge tone={message.status === 'ignored' ? 'neutral' : message.status === 'failed' ? 'danger' : 'success'}>{t(message.status_label)}</Badge>
                      {message.ad_name && <Badge tone="brand">{message.ad_name}</Badge>}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-sm text-ink">{message.text}</p>
                    <p className="mt-1 text-xs text-ink-muted">{formatDateTime(message.provider_sent_at || message.created_at)}</p>
                    {message.post_url && <a className="mt-1 inline-block text-xs font-semibold text-brand-600 hover:underline" href={message.post_url} target="_blank" rel="noreferrer">{t('Открыть публикацию')}</a>}
                  </div>
                  {message.child && <Link className="text-sm font-semibold text-brand-600 hover:underline" to={`/children/${message.child.id}`}>{message.child.name}</Link>}
                  {message.lead && <Link className="text-sm font-semibold text-brand-600 hover:underline" to={`/leads/${message.lead.id}`}>{message.lead.name}</Link>}
                </div>
                {message.resolution_note && <p className="text-[13px] text-ink-muted">{message.resolution_note}</p>}
                {message.status === 'ignored' && (
                  <Button
                    variant="secondary"
                    loading={busy === `promote-${message.id}`}
                    onClick={() => action(message, 'promote', () => api.post(`messaging/instagram/inbox/${message.id}/promote/`))}
                  >
                    {t('Создать заявку вручную')}
                  </Button>
                )}
                {message.candidates?.length > 0 && (
                  <div className="flex flex-wrap gap-2 rounded-xl border border-warning-200 bg-warning-50 p-3">
                    {message.candidates.map(candidate => (
                      <Button
                        key={`${candidate.type}-${candidate.id}`}
                        variant="secondary"
                        loading={busy === `bind-${message.id}`}
                        onClick={() => action(message, 'bind', () => api.post(`messaging/instagram/inbox/${message.id}/resolve/`, { [`${candidate.type}_id`]: candidate.id }))}
                      >
                        {t('Ребёнок')}: {candidate.name}
                      </Button>
                    ))}
                  </div>
                )}
                <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
                  <Field className="min-w-0 flex-1" label={message.kind === 'comment' ? t('Публичный ответ') : t('Ответ в Direct')}>
                    {({ id }) => <Input id={id} maxLength={1000} value={reply[message.id] || ''} onChange={event => setReply(current => ({ ...current, [message.id]: event.target.value }))} placeholder={message.kind === 'comment' ? t('Без телефонов, имён детей и данных об оплате') : t('Напишите ответ')} />}
                  </Field>
                  <Button
                    variant="primary"
                    icon={Send}
                    disabled={!(reply[message.id] || '').trim()}
                    loading={busy === `reply-${message.id}`}
                    onClick={() => action(message, 'reply', () => api.post(`messaging/instagram/inbox/${message.id}/reply/`, { body: reply[message.id] }))}
                  >
                    {t('Ответить')}
                  </Button>
                </div>
                {message.reply_text && <p className="rounded-lg bg-success-50 px-3 py-2 text-sm text-success-800">{t('Ответ отправлен')}: {message.reply_text}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}

export function MessagingTemplates() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)
  const [params, setParams] = useSearchParams()
  const load = useCallback(() => api.get('messaging/templates/').then(res => setRows(res.data)).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!rows) return <Skeleton className="h-96" />
  const row = rows.find(r => r.event === params.get('event')) || rows[0]
  function choose(event) {
    const next = new URLSearchParams(params)
    next.set('event', event)
    setParams(next, { replace: true })
  }
  return (
    <div>
      <PageHeader description={t('Тексты писем родителям на двух языках — под тон вашего центра. Язык выбирается по кабинету родителя, иначе русский. Ссылка «отписаться» добавляется сама.')} />
      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        {/* Список писем; на телефоне — строкой с прокруткой. */}
        <Card padded={false} className="lg:sticky lg:top-24">
          <ul className="flex gap-1 overflow-x-auto p-2 lg:flex-col lg:overflow-visible">
            {rows.map(r => {
              const custom = r.email.ru.customized || r.email.kk.customized
              return (
                <li key={r.event} className="shrink-0 lg:shrink">
                  <button
                    type="button"
                    onClick={() => choose(r.event)}
                    aria-current={r.event === row.event || undefined}
                    className={cn(
                      'flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left text-[13px] transition-colors',
                      r.event === row.event ? 'bg-brand-50 font-semibold text-brand-700' : 'text-ink hover:bg-surface-muted',
                    )}
                  >
                    <Mail className="size-4 shrink-0 opacity-70" />
                    <span className="min-w-0 flex-1 whitespace-nowrap lg:whitespace-normal">{t(r.label)}</span>
                    {custom && <span className="size-1.5 shrink-0 rounded-full bg-brand-500" title={t('Свой текст центра')} />}
                  </button>
                </li>
              )
            })}
          </ul>
        </Card>
        <TemplateEditor key={row.event} row={row} onSaved={load} />
      </div>
    </div>
  )
}

function TemplateEditor({ row, onSaved }) {
  const toast = useToast()
  const [lang, setLang] = useState('ru')
  const current = row.email[lang]
  const [draft, setDraft] = useState(current)
  const [saving, setSaving] = useState(false)
  const bodyRef = useRef(null)
  // Сменили язык или пришли новые данные — черновик заново.
  const [shown, setShown] = useState({ lang, current })
  if (shown.lang !== lang || shown.current !== current) {
    setShown({ lang, current })
    setDraft(current)
  }
  const dirty = draft.subject !== current.subject || draft.body !== current.body

  // Подстановка — в текст, туда, где стоит курсор.
  function insert(key) {
    const el = bodyRef.current
    const token = `{${key}}`
    const at = el ? el.selectionStart : draft.body.length
    const end = el ? el.selectionEnd : at
    setDraft({ ...draft, body: draft.body.slice(0, at) + token + draft.body.slice(end) })
    requestAnimationFrame(() => {
      if (!el) return
      el.focus()
      el.setSelectionRange(at + token.length, at + token.length)
    })
  }

  async function save() {
    setSaving(true)
    try {
      await api.put(`messaging/templates/${row.event}/${lang}/`, { subject: draft.subject, body: draft.body })
      toast.success(t('Текст сохранён'))
      onSaved()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function reset() {
    try {
      await api.delete(`messaging/templates/${row.event}/${lang}/`)
      toast.success(t('Вернули текст по умолчанию'))
      onSaved()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  return (
    <Card>
      <CardHeader
        title={t(row.label)}
        description={t('Служебное письмо — уходит родителям с согласием на уведомления.')}
        actions={
          <div className="inline-flex rounded-lg border border-line p-0.5">
            {LANGS.map(l => (
              <button key={l.key} type="button" onClick={() => setLang(l.key)} aria-pressed={lang === l.key} className={cn('rounded-md px-3 py-1 text-[13px] font-semibold', lang === l.key ? 'bg-brand-50 text-brand-700' : 'text-ink-muted')}>
                {l.label}
              </button>
            ))}
          </div>
        }
      />
      <div className="space-y-3">
        <Field label={t('Тема письма')}>
          {({ id }) => <Input id={id} value={draft.subject} onChange={e => setDraft({ ...draft, subject: e.target.value })} maxLength={200} />}
        </Field>
        <Field label={t('Текст')}>
          {({ id }) => <Textarea ref={bodyRef} id={id} rows={8} value={draft.body} onChange={e => setDraft({ ...draft, body: e.target.value })} />}
        </Field>
        <div>
          <p className="mb-1.5 text-[12px] text-ink-muted">{t('Подстановки — нажмите, чтобы вставить в текст:')}</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(row.variables).map(([key, label]) => (
              <button key={key} type="button" onClick={() => insert(key)} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-surface-muted px-2 py-1 text-[12px] text-ink-muted transition-colors hover:border-brand-400 hover:text-ink">
                <code className="font-semibold text-brand-600">{`{${key}}`}</code>{t(label)}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
          {current.customized ? <Badge tone="brand">{t('Свой текст центра')}</Badge> : <span className="text-[12px] text-ink-subtle">{t('Текст по умолчанию')}</span>}
          <span className="ml-auto flex gap-2">
            {dirty && <Button variant="ghost" onClick={() => setDraft(current)}>{t('Отменить')}</Button>}
            {!dirty && current.customized && <Button variant="ghost" icon={Undo2} onClick={reset}>{t('Вернуть по умолчанию')}</Button>}
            <Button variant="primary" onClick={save} loading={saving} disabled={!dirty}>{t('Сохранить')}</Button>
          </span>
        </div>
      </div>
    </Card>
  )
}

export function MessagingSettings() {
  const toast = useToast()
  const [form, setForm] = useState(null)
  const [saved, setSaved] = useState(null)
  const [error, setError] = useState(false)
  const [saving, setSaving] = useState(false)
  const apply = data => { setForm(data); setSaved(data) }
  const load = useCallback(() => api.get('messaging/settings/').then(res => apply(res.data)).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!form) return <Skeleton className="h-64" />

  const hours = Array.from({ length: 24 }, (_, h) => h)
  const dirty = JSON.stringify(form) !== JSON.stringify(saved)
  // Включённые — в порядке попыток, выключенные — ниже.
  const byKey = Object.fromEntries(form.available_channels.map(c => [c.key, c]))
  const ordered = [...form.channels, ...form.available_channels.map(c => c.key).filter(k => !form.channels.includes(k))]
  function toggleChannel(key, on) {
    setForm({ ...form, channels: on ? [...form.channels, key] : form.channels.filter(c => c !== key) })
  }
  function move(key, delta) {
    const channels = [...form.channels]
    const from = channels.indexOf(key)
    const to = from + delta
    if (to < 0 || to >= channels.length) return
    ;[channels[from], channels[to]] = [channels[to], channels[from]]
    setForm({ ...form, channels })
  }

  async function save() {
    setSaving(true)
    try {
      const res = await api.put('messaging/settings/', form)
      apply(res.data)
      toast.success(t('Настройки сохранены'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <PageHeader description={t('Когда и через что система пишет родителям.')} />
      <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader
            title={t('Автоуведомления')}
            description={t('Включите только нужные события. Сообщения учитывают согласие родителя и тихие часы.')}
          />
          <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <div>
              <Checkbox
                checked={form.rules.payment_enabled}
                onChange={e => setForm({ ...form, rules: { ...form.rules, payment_enabled: e.target.checked } })}
                label={<span className="text-sm text-ink">{t('Напоминать о просроченной оплате')}</span>}
              />
            </div>
            <div>
              <Checkbox
                checked={form.rules.subscription_enabled}
                onChange={e => setForm({ ...form, rules: { ...form.rules, subscription_enabled: e.target.checked } })}
                label={<span className="text-sm text-ink">{t('Напоминать об окончании абонемента')}</span>}
              />
            </div>
            <div>
              <Checkbox
                checked={form.rules.lesson_changes_enabled}
                onChange={e => setForm({ ...form, rules: { ...form.rules, lesson_changes_enabled: e.target.checked } })}
                label={<span className="text-sm text-ink">{t('Сообщать об отмене и переносе')}</span>}
              />
            </div>
            <div className="flex flex-wrap items-end gap-3 sm:col-span-2">
              <Checkbox
                checked={form.rules.lesson_reminder_enabled}
                onChange={e => setForm({ ...form, rules: { ...form.rules, lesson_reminder_enabled: e.target.checked } })}
                label={<span className="text-sm text-ink">{t('Напоминать о ближайшем занятии')}</span>}
              />
              <Field label={t('За сколько часов')} className="w-40">
                {({ id }) => <Input id={id} type="number" min="1" max="168" value={form.rules.lesson_reminder_hours} onChange={e => setForm({ ...form, rules: { ...form.rules, lesson_reminder_hours: Number(e.target.value) } })} />}
              </Field>
            </div>
          </div>
          <div className="mt-4 rounded-lg bg-surface-muted px-3 py-3 text-[13px] text-ink-muted">
            <p className="font-semibold text-ink">{t('Оценка на неделю: около {n} сообщений', { n: form.weekly_preview.total })}</p>
            <p className="mt-1">{t('Оплата: {payment}, абонементы: {subscriptions}, занятия: {lessons}', {
              payment: form.weekly_preview.payment,
              subscriptions: form.weekly_preview.subscription,
              lessons: form.weekly_preview.lesson_reminder,
            })}</p>
            <p className="mt-1 text-ink-subtle">{t(form.weekly_preview.note)}</p>
          </div>
        </Card>
        <Card>
            <CardHeader title={t('Каналы')} description={t('Пробуем по порядку: первый, через который удалось отправить, — последний.')} />
            <ul className="divide-y divide-line">
              {ordered.map(key => {
                const channel = byKey[key]
                const position = form.channels.indexOf(key)
                return (
                  <li key={key} className="flex items-start gap-2 py-2.5 first:pt-0 last:pb-0">
                    <span className="mt-0.5 w-5 text-center text-[13px] font-bold text-ink-subtle">{position >= 0 ? position + 1 : ''}</span>
                    <div className="min-w-0 flex-1">
                      <Checkbox
                        checked={position >= 0}
                        onChange={e => toggleChannel(key, e.target.checked)}
                        label={<span className="text-sm text-ink">{t(channel.label)}</span>}
                      />
                      {!channel.connected && <p className="mt-1 pl-7 text-[12px] text-ink-muted">{t(channel.reason)} — {t('пока пропускается')}</p>}
                    </div>
                    {position >= 0 && (
                      <span className="flex gap-1">
                        <Button size="icon" variant="ghost" aria-label={t('Выше')} disabled={position === 0} onClick={() => move(key, -1)}><ArrowUp className="size-4" /></Button>
                        <Button size="icon" variant="ghost" aria-label={t('Ниже')} disabled={position === form.channels.length - 1} onClick={() => move(key, 1)}><ArrowDown className="size-4" /></Button>
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
        </Card>
        <Card>
          <CardHeader title={t('Тихие часы')} description={t('Ночью не пишем — сообщение уйдёт утром. По времени центра.')} />
          <div className="flex flex-wrap items-end gap-3">
            <span className="flex size-[38px] items-center justify-center rounded-md bg-surface-muted text-ink-subtle"><Moon className="size-[18px]" /></span>
            <Field label={t('С')} className="w-28">
              {({ id }) => <Select id={id} value={form.quiet_from} onChange={e => setForm({ ...form, quiet_from: Number(e.target.value) })}>{hours.map(h => <option key={h} value={h}>{h}:00</option>)}</Select>}
            </Field>
            <Field label={t('До')} className="w-28">
              {({ id }) => <Select id={id} value={form.quiet_to} onChange={e => setForm({ ...form, quiet_to: Number(e.target.value) })}>{hours.map(h => <option key={h} value={h}>{h}:00</option>)}</Select>}
            </Field>
          </div>
        </Card>
        <Card>
          <CardHeader title={t('Ответ на письма')} description={t('Письма приходят от имени центра; ответ родителя придёт на этот адрес.')} />
          <Field label={t('Email центра')}>
            {({ id }) => <Input id={id} type="email" placeholder="info@trueballet.kz" value={form.reply_to} onChange={e => setForm({ ...form, reply_to: e.target.value })} />}
          </Field>
        </Card>
      </div>
      <WhatsAppSettings />
      <InstagramSettings />
      {/* Место под панель, чтобы она не закрывала последнюю карточку. */}
      {dirty && <div className="h-20" aria-hidden />}
      {/* Как на «Организации»: панель — только когда есть что сохранить. */}
      <div className="sticky bottom-4 z-20 h-0">
        <div
          className={cn(
            'absolute bottom-0 left-0 flex w-full justify-center transition-all duration-200',
            dirty ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-4 opacity-0',
          )}
          aria-hidden={!dirty}
        >
          <div className="flex w-full flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 shadow-pop sm:w-auto">
            <span className="size-2 shrink-0 rounded-full bg-warning-600" />
            <p className="text-[13px] font-semibold text-ink sm:mr-4">{t('Есть несохранённые изменения')}</p>
            <span className="ml-auto flex gap-2">
              <Button variant="ghost" tabIndex={dirty ? 0 : -1} onClick={() => setForm(saved)}>{t('Отменить')}</Button>
              <Button variant="primary" onClick={save} loading={saving} tabIndex={dirty ? 0 : -1}>{t('Сохранить')}</Button>
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function WhatsAppSettings() {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState('')
  const load = useCallback(() => api.get('messaging/whatsapp/').then(response => setData(response.data)), [])
  useEffect(() => { load().catch(() => {}) }, [load])

  async function action(name, request) {
    setBusy(name)
    try {
      const response = await request()
      setData(response.data)
      toast.success(name === 'save' ? t('Подключение сохранено') : name === 'test' ? t('Подключение работает') : t('Шаблоны синхронизированы'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setBusy('')
    }
  }

  if (!data) return <Skeleton className="mt-4 h-72" />
  const connected = data.status === 'connected'
  return (
    <Card className="mt-4">
      <CardHeader
        title={t('WhatsApp Business')}
        description={t('Подключение Meta Cloud API, проверка и статусы шаблонов.')}
        actions={<Badge tone={connected ? 'success' : data.status === 'error' ? 'danger' : 'neutral'} dot>{t(connected ? 'Подключён' : data.status === 'error' ? 'Ошибка подключения' : 'Не подключён')}</Badge>}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <Field label={t('Режим')}>
            {({ id }) => (
              <Select id={id} value={data.mode} onChange={event => setData({ ...data, mode: event.target.value })}>
                <option value="console">{t('Тестовый режим — без отправки')}</option>
                <option value="meta">Meta Cloud API</option>
              </Select>
            )}
          </Field>
          {data.mode === 'meta' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="WABA ID">{({ id }) => <Input id={id} value={data.waba_id} onChange={event => setData({ ...data, waba_id: event.target.value })} />}</Field>
              <Field label="Phone number ID">{({ id }) => <Input id={id} value={data.phone_number_id} onChange={event => setData({ ...data, phone_number_id: event.target.value })} />}</Field>
              <Field label={t('Номер бизнеса')}>{({ id }) => <Input id={id} value={data.business_phone} onChange={event => setData({ ...data, business_phone: event.target.value })} placeholder="+7 700 000 00 00" />}</Field>
              <Field label={t('Токен доступа')} hint={data.has_token ? t('Токен уже сохранён. Оставьте пустым, чтобы не менять.') : ''}>
                {({ id }) => <Input id={id} type="password" value={data.access_token || ''} onChange={event => setData({ ...data, access_token: event.target.value })} autoComplete="new-password" />}
              </Field>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => action('save', () => api.put('messaging/whatsapp/', data))} loading={busy === 'save'}>{t('Сохранить подключение')}</Button>
            <Button variant="primary" icon={CheckCircle2} onClick={() => action('test', () => api.post('messaging/whatsapp/test/'))} loading={busy === 'test'}>{t('Проверить подключение')}</Button>
          </div>
          {data.last_error && <p className="text-sm text-danger-600">{data.last_error}</p>}
          {data.webhook_verify_token && (
            <div className="rounded-md bg-surface-muted p-3 text-xs text-ink-muted">
              <p><b className="text-ink">Webhook:</b> {window.location.origin}/api/v1/messaging/whatsapp/webhook/</p>
              <p className="mt-1 break-all"><b className="text-ink">Verify token:</b> {data.webhook_verify_token}</p>
            </div>
          )}
        </div>
        <div>
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-bold text-ink">{t('Шаблоны Meta')}</p>
              <p className="text-xs text-ink-muted">{t('Неодобренные шаблоны отправить нельзя.')}</p>
            </div>
            <Button size="sm" icon={RefreshCw} disabled={!connected} loading={busy === 'sync'} onClick={() => action('sync', () => api.post('messaging/whatsapp/templates/sync/'))}>{t('Синхронизировать')}</Button>
          </div>
          {data.templates.length ? (
            <ul className="max-h-72 divide-y divide-line overflow-y-auto rounded-lg border border-line">
              {data.templates.map(template => (
                <li key={`${template.event}-${template.language}`} className="flex items-start gap-3 px-3 py-2.5">
                  <MessageCircle className="mt-0.5 size-4 shrink-0 text-success-600" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-ink">{t(template.event_label)} · {template.language.toUpperCase()}</p>
                    {template.rejection_reason && <p className="mt-0.5 text-xs text-danger-600">{template.rejection_reason}</p>}
                  </div>
                  <Badge tone={template.status === 'approved' ? 'success' : template.status === 'rejected' ? 'danger' : template.status === 'pending' ? 'warning' : 'neutral'}>{t(template.status_label)}</Badge>
                </li>
              ))}
            </ul>
          ) : <p className="rounded-lg border border-dashed border-line p-6 text-center text-sm text-ink-muted">{t('Проверьте подключение, чтобы загрузить шаблоны.')}</p>}
        </div>
      </div>
    </Card>
  )
}

function InstagramSettings() {
  const toast = useToast()
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState('')
  const load = useCallback(() => api.get('messaging/instagram/').then(response => setData(response.data)), [])
  useEffect(() => { load().catch(() => {}) }, [load])

  async function action(name, request) {
    setBusy(name)
    try {
      const response = await request()
      setData(response.data)
      toast.success(name === 'save' ? t('Подключение сохранено') : t('Подключение работает'))
    } catch (error) {
      toast.error(apiErrorMessage(error))
    } finally {
      setBusy('')
    }
  }

  if (!data) return <Skeleton className="mt-4 h-64" />
  const connected = data.status === 'connected'
  return (
    <Card className="mt-4">
      <CardHeader
        title={t('Instagram Business')}
        description={t('Нужен профессиональный Instagram-аккаунт, связанный со страницей Facebook.')}
        actions={<Badge tone={connected ? 'success' : data.status === 'error' ? 'danger' : 'neutral'} dot>{t(connected ? 'Подключён' : data.status === 'error' ? 'Ошибка подключения' : 'Не подключён')}</Badge>}
      />
      {data.token_expiring && <p className="mb-4 rounded-lg bg-warning-50 px-3 py-2 text-sm text-warning-800">{t('Токен Instagram скоро истечёт или уже истёк. Обновите подключение, иначе новые заявки перестанут поступать.')}</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <Field label={t('Режим')}>
            {({ id }) => (
              <Select id={id} value={data.mode} onChange={event => setData({ ...data, mode: event.target.value })}>
                <option value="console">{t('Тестовый режим — без отправки')}</option>
                <option value="meta">Instagram Graph API</option>
              </Select>
            )}
          </Field>
          {data.mode === 'meta' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Instagram Business Account ID">{({ id }) => <Input id={id} value={data.instagram_account_id} onChange={event => setData({ ...data, instagram_account_id: event.target.value })} />}</Field>
              <Field label="Facebook Page ID">{({ id }) => <Input id={id} value={data.facebook_page_id} onChange={event => setData({ ...data, facebook_page_id: event.target.value })} />}</Field>
              <Field label={t('Токен доступа')} hint={data.has_token ? t('Токен уже сохранён. Оставьте пустым, чтобы не менять.') : ''}>{({ id }) => <Input id={id} type="password" value={data.access_token || ''} onChange={event => setData({ ...data, access_token: event.target.value })} />}</Field>
              <Field label={t('Токен действует до')}>{({ id }) => <Input id={id} type="datetime-local" value={data.token_expires_at ? data.token_expires_at.slice(0, 16) : ''} onChange={event => setData({ ...data, token_expires_at: event.target.value || null })} />}</Field>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => action('save', () => api.put('messaging/instagram/', data))} loading={busy === 'save'}>{t('Сохранить подключение')}</Button>
            <Button variant="primary" icon={CheckCircle2} onClick={() => action('test', () => api.post('messaging/instagram/test/'))} loading={busy === 'test'}>{t('Проверить подключение')}</Button>
          </div>
          {data.last_error && <p className="text-sm text-danger-600">{data.last_error}</p>}
        </div>
        <div className="rounded-lg bg-surface-muted p-4 text-sm text-ink-muted">
          <p className="font-bold text-ink">{t('Что включить в Meta')}</p>
          <p className="mt-2">{t('Подпишите приложение на события messages, comments и live_comments.')}</p>
          <p className="mt-3 break-all"><b className="text-ink">Webhook:</b> {window.location.origin}/api/v1/messaging/instagram/webhook/</p>
          {data.webhook_verify_token && <p className="mt-1 break-all"><b className="text-ink">Verify token:</b> {data.webhook_verify_token}</p>}
          {!connected && <p className="mt-3 text-warning-800">{t('Пока аккаунт не подключён, заявки из Instagram нужно создавать вручную.')}</p>}
        </div>
      </div>
    </Card>
  )
}
