import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowUp, ChevronDown, Moon, Send, Undo2 } from 'lucide-react'
import api from '../api/axios'
import { STATUS_TONE } from '../components/messaging/status'
import {
  Badge, Button, Card, CardHeader, Checkbox, EmptyState, ErrorState, Field, FilterSelect, Input, PageHeader,
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

export function MessagingJournal() {
  const [params, setParams] = useSearchParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [open, setOpen] = useState(null)
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

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!data) return <Skeleton className="h-96" />

  const parentName = filters.parent && data.results[0]?.parent.name

  return (
    <div>
      <PageHeader description={t('Что система написала родителям: когда, каким каналом, что вышло. Отписка и отказы — здесь же.')} />
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <FilterSelect label={t('Событие')} value={filters.event} onChange={v => setFilter('event', v)} options={[['', t('Все события')], ...data.events.map(e => [e.key, t(e.label)])]} />
        <FilterSelect label={t('Статус')} value={filters.status} onChange={v => setFilter('status', v)} options={[['', t('Все статусы')], ...data.statuses.map(s => [s.key, t(s.label)])]} />
        {filters.parent && (
          <Button size="sm" variant="ghost" onClick={() => setFilter('parent', '')}>
            {parentName ? t('Родитель: {name} ✕', { name: parentName }) : t('Сбросить родителя ✕')}
          </Button>
        )}
      </div>
      <Card padded={false} className="mt-4">
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

export function MessagingTemplates() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)
  const load = useCallback(() => api.get('messaging/templates/').then(res => setRows(res.data)).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!rows) return <Skeleton className="h-96" />
  return (
    <div>
      <PageHeader description={t('Тексты писем родителям на двух языках — под тон вашего центра. Язык выбирается по кабинету родителя, иначе русский. Ссылка «отписаться» добавляется сама.')} />
      <div className="space-y-4">
        {rows.map(row => <TemplateCard key={row.event} row={row} onSaved={load} />)}
      </div>
    </div>
  )
}

function TemplateCard({ row, onSaved }) {
  const toast = useToast()
  const [lang, setLang] = useState('ru')
  const current = row.email[lang]
  const [draft, setDraft] = useState(current)
  const [saving, setSaving] = useState(false)
  // Сменили язык или пришли новые данные — черновик заново.
  const [shown, setShown] = useState({ lang, current })
  if (shown.lang !== lang || shown.current !== current) {
    setShown({ lang, current })
    setDraft(current)
  }
  const dirty = draft.subject !== current.subject || draft.body !== current.body

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
              <button key={l.key} type="button" onClick={() => setLang(l.key)} className={cn('rounded-md px-3 py-1 text-[13px] font-semibold', lang === l.key ? 'bg-brand-50 text-brand-700' : 'text-ink-muted')}>
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
          {({ id }) => <Textarea id={id} rows={6} value={draft.body} onChange={e => setDraft({ ...draft, body: e.target.value })} />}
        </Field>
        <p className="text-[12px] text-ink-muted">
          {t('Подстановки')}: {Object.entries(row.variables).map(([key, label]) => (
            <span key={key} className="mr-2 inline-block"><code className="rounded bg-surface-muted px-1">{`{${key}}`}</code> {t(label)}</span>
          ))}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {current.customized && <Badge tone="brand">{t('Свой текст центра')}</Badge>}
          <span className="ml-auto flex gap-2">
            {current.customized && <Button variant="ghost" icon={Undo2} onClick={reset}>{t('Вернуть по умолчанию')}</Button>}
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
  const [error, setError] = useState(false)
  const [saving, setSaving] = useState(false)
  const load = useCallback(() => api.get('messaging/settings/').then(res => setForm(res.data)).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!form) return <Skeleton className="h-64" />

  const hours = Array.from({ length: 24 }, (_, h) => h)
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
      setForm(res.data)
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
        <div className="space-y-4">
        <Card>
          <CardHeader title={t('Тихие часы')} description={t('Ночью не пишем — сообщение уйдёт утром. По времени центра.')} />
          <div className="flex flex-wrap items-end gap-3">
            <Moon className="mb-2.5 size-5 text-ink-subtle" />
            <Field label={t('С')}>
              {({ id }) => <Select id={id} value={form.quiet_from} onChange={e => setForm({ ...form, quiet_from: Number(e.target.value) })}>{hours.map(h => <option key={h} value={h}>{h}:00</option>)}</Select>}
            </Field>
            <Field label={t('До')}>
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
      </div>
      <div className="mt-4 flex justify-end">
        <Button variant="primary" onClick={save} loading={saving}>{t('Сохранить')}</Button>
      </div>
    </div>
  )
}
