import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowRight, CalendarClock, CheckSquare, ChevronRight, History, Loader2, Newspaper, RefreshCw, Sprout, TrendingDown, TrendingUp, X } from 'lucide-react'
import api from '../api/axios'
import { AIBadge } from '../components/ai/ai'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton, apiErrorMessage, cn, formatDateTime, useToast } from '../ui'
import { locale, plural, t, useLang } from '../i18n'

/*
 * Еженедельный дайджест (TRU-163): что сделать на этой неделе. Не второй
 * дашборд — сверху что изменилось и 3–4 главных совета с цифрами, ниже всё
 * остальное и архив прошлых недель. Цифры — из агрегатов CRM, не от модели.
 */

const POLL_MS = 4000

const PRIORITY = {
  high: { get label() { return t('Важно') }, tone: 'danger' },
  medium: { get label() { return t('На этой неделе') }, tone: 'warning' },
  low: { get label() { return t('Можно позже') }, tone: 'neutral' },
}

function weekdayName(index) {
  // 5 октября 2026 — понедельник: от него берём день недели нужного номера.
  return new Date(2026, 9, 5 + index).toLocaleString(locale, { weekday: 'long' })
}

function dayMonth(iso) {
  const [year, month, day] = iso.slice(0, 10).split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleString(locale, { day: 'numeric', month: 'long' })
}

function number(value) {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(value)
}

/** Цифра факта: «42 %», «125 000 ₸» — по подписи из агрегатов. */
function factValue({ value, label }) {
  if (/%\s*$/.test(label)) return `${number(value)} %`
  if (/выручк|долг|₸/i.test(label)) return `${number(value)} ₸`
  return number(value)
}

/** Подпись факта без раздела: «Растяжка 5–10, Орбита: заполняемость, %». */
function shortLabel(label) {
  const parts = label.split(' · ')
  const text = parts.length > 1 ? parts.slice(1).join(' · ') : label
  // Старые дайджесты могли сохранить внутренний candidate_key рядом с названием группы.
  const withoutTechnicalKeys = text
    .replace(/\b[0-9a-f]{12,64}\b,?\s*/gi, '')
    .replace(/·\s*,/g, '· ')
  const localized = withoutTechnicalKeys.replace(
    /(^| · |, |: )([^·,:]+)/g,
    (_, separator, value) => `${separator}${t(value.trim())}`,
  )
  // «%» уже стоит у самой цифры.
  return localized.replace(/, %$/, '')
}

export default function Digest() {
  const language = useLang()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('id')
  const [data, setData] = useState(null)
  // Выпуск из архива: держим вместе с id, чтобы не показывать чужой при переключении.
  const [loaded, setLoaded] = useState(null)
  const [error, setError] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(() => api.get('ai/digests/', { params: { language } }).then(res => { setData(res.data); setError(false) }).catch(() => setError(true)), [language])
  useEffect(() => { load() }, [load])

  // Собирается — опрашиваем, пока не будет готов.
  useEffect(() => {
    if (!data?.building) return undefined
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [data?.building, load])

  useEffect(() => {
    if (!selectedId) return
    api.get(`ai/digests/${selectedId}/`, { params: { language } }).then(res => setLoaded(res.data)).catch(() => setParams({}))
  }, [selectedId, setParams, language])
  const selected = selectedId && loaded?.id === selectedId ? loaded : null

  async function refresh() {
    setRefreshing(true)
    try {
      const res = await api.post('ai/digests/', { language })
      if (!res.data.created) toast.success(t('Дайджест уже собирается'))
      setParams({})
      await load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setRefreshing(false)
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!data) return <Skeleton className="h-96" />

  const schedule = t('Приходит каждую неделю: {day}, {hour}:00 по времени центра.', {
    day: weekdayName(data.schedule.weekday),
    hour: data.schedule.hour,
  })
  const shown = selected || data.latest
  const building = Boolean(data.building)

  return (
    <div>
      <PageHeader
        title={t('Дайджест недели')}
        description={`${t('Что сделать на этой неделе — по данным центра.')} ${schedule}`}
        actions={
          <Button icon={RefreshCw} loading={refreshing || building} onClick={refresh}>
            {building ? t('Собираем…') : t('Обновить')}
          </Button>
        }
      />

      <div className="space-y-4">
        {building && data.latest && !selected && (
          <Banner tone="info"><Loader2 className="size-4 shrink-0 animate-spin" /> {t('Собираем новый дайджест — обычно это меньше минуты. Пока показан прошлый.')}</Banner>
        )}
        {data.notice && !selected && <Banner tone="warning">{data.notice.text || t('Новый дайджест не собрался — повторим завтра.')}</Banner>}
        {selected && (
          <button type="button" onClick={() => setParams({})} className="inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:underline">
            ← {t('К последнему дайджесту')}
          </button>
        )}

        {selectedId && !selected ? (
          <Skeleton className="h-64" />
        ) : !shown ? (
          <Card>
            {building ? (
              <EmptyState icon={Newspaper} title={t('Собираем первый дайджест')} description={t('Обычно это меньше минуты — страница обновится сама.')} />
            ) : (
              <EmptyState icon={CalendarClock} title={t('Дайджестов пока нет')} description={schedule} action={<Button variant="primary" icon={RefreshCw} onClick={refresh} loading={refreshing}>{t('Собрать сейчас')}</Button>} />
            )}
          </Card>
        ) : shown.status === 'insufficient_data' ? (
          <Card>
            <EmptyState
              icon={Sprout}
              title={t('Данных пока мало')}
              description={t('Советы появятся, когда в группах будет хотя бы {needed} детей — сейчас {n}. Советовать по паре человек — значит гадать. Вернёмся через неделю.', { needed: shown.content.needed, n: shown.content.active_children })}
            />
          </Card>
        ) : (
          <DigestView digest={shown} />
        )}

        <Archive items={data.archive} activeId={shown?.id} onOpen={id => setParams(id === data.latest?.id ? {} : { id })} />
      </div>
    </div>
  )
}

function Banner({ tone, children }) {
  const tones = {
    info: 'bg-info-50 text-info-600',
    warning: 'bg-warning-50 text-warning-700',
  }
  return <div className={cn('flex items-center gap-2 rounded-xl px-4 py-3 text-[13px] font-medium', tones[tone])}>{children}</div>
}

function DigestView({ digest }) {
  const { content } = digest
  const toast = useToast()
  const [taskItem, setTaskItem] = useState(null)
  const [dismissed, setDismissed] = useState([])
  const visible = content.items.filter(item => !dismissed.includes(item.id))
  const highlights = content.highlights.filter(item => !dismissed.includes(item.id))
  const rest = visible.filter(item => !highlights.some(h => h.id === item.id))

  async function dismiss(item) {
    try {
      await api.post(`ai/digests/${digest.id}/dismiss/`, { item_id: item.id })
      setDismissed(current => [...current, item.id])
      toast.success(t('Рекомендация скрыта'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  return (
    <>
      <p className="flex flex-wrap items-center gap-2 px-1 text-[13px] text-ink-muted">
        <AIBadge />
        {t('Неделя с {date}', { date: dayMonth(digest.week_start) })} · {t('собран {when}', { when: formatDateTime(digest.ready_at) })}
      </p>

      <Changes changes={content.changes} />

      <section>
        <h2 className="mb-2 px-1 text-[15px] font-bold text-ink">{t('Главное')}</h2>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {highlights.map(item => (
            <Advice key={item.id} item={item} onTask={() => setTaskItem(item)} onDismiss={() => dismiss(item)} />
          ))}
        </div>
      </section>

      {rest.length > 0 && (
        <Card>
          <CardHeader title={t('Ещё советы')} />
          <ul className="divide-y divide-line">
            {rest.map(item => (
              <li key={item.id} className="py-3">
                <p className="text-sm font-semibold text-ink">{item.title}</p>
                <p className="mt-0.5 text-[13px] text-ink-muted">{item.action}</p>
                <div className="mt-2 flex gap-2">
                  <Button size="sm" variant="secondary" icon={CheckSquare} onClick={() => setTaskItem(item)}>{t('Поставить задачу')}</Button>
                  <Button size="sm" variant="ghost" icon={X} onClick={() => dismiss(item)}>{t('Не актуально')}</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {content.failed_blocks > 0 && (
        <p className="px-1 text-[13px] text-ink-muted">{t('Часть блоков не собралась — в следующий раз попробуем снова.')}</p>
      )}
      {taskItem && <DigestTaskModal digestId={digest.id} item={taskItem} onClose={() => setTaskItem(null)} />}
    </>
  )
}

function Changes({ changes }) {
  if (!changes) return null
  const since = dayMonth(changes.since)
  if (changes.unchanged) {
    return (
      <Card className="!py-4">
        <p className="text-sm text-ink"><span className="font-semibold">{t('С {date} ничего заметно не изменилось.', { date: since })}</span> {t('Советы те же — если уже взялись за них, продолжайте.')}</p>
      </Card>
    )
  }
  return (
    <Card>
      <CardHeader title={t('Что изменилось с {date}', { date: since })} />
      <ul className="space-y-2 text-sm">
        {changes.values.map(v => (
          <li key={v.key} className="flex flex-wrap items-center gap-x-2">
            {v.after > v.before ? <TrendingUp className="size-4 text-success-600" /> : <TrendingDown className="size-4 text-danger-600" />}
            <span className="text-ink-muted">{shortLabel(v.label)}:</span>
            <span className="font-semibold text-ink">{factValue({ value: v.before, label: v.label })} → {factValue({ value: v.after, label: v.label })}</span>
          </li>
        ))}
        {changes.new.map(title => (
          <li key={`new-${title}`} className="flex items-center gap-2"><Badge tone="info">{t('Новое')}</Badge><span className="text-ink">{title}</span></li>
        ))}
        {changes.gone.map(title => (
          <li key={`gone-${title}`} className="flex items-center gap-2 text-ink-muted"><Badge>{t('Уже не актуально')}</Badge><span className="line-through">{title}</span></li>
        ))}
      </ul>
    </Card>
  )
}

function Advice({ item, onTask, onDismiss }) {
  const priority = PRIORITY[item.priority] || PRIORITY.low
  return (
    <Card className="flex flex-col">
      <div className="mb-2"><Badge tone={priority.tone}>{priority.label}</Badge></div>
      <h3 className="text-[15px] font-bold leading-snug text-ink">{item.title}</h3>
      <div className="mt-3 flex flex-wrap gap-2">
        {item.evidence.map(e => (
          <div key={e.key} className="min-w-0 rounded-lg bg-surface-muted px-3 py-2">
            <p className="text-lg font-bold leading-none text-ink">{factValue(e)}</p>
            <p className="mt-1 text-[12px] leading-snug text-ink-muted">{shortLabel(e.label)}</p>
          </div>
        ))}
      </div>
      <p className="mt-3 flex gap-2 text-sm font-medium text-ink">
        <ArrowRight className="mt-0.5 size-4 shrink-0 text-brand-600" />
        <span>{item.action}</span>
      </p>
      <p className="mt-1.5 pl-6 text-[13px] text-ink-muted">{item.rationale}</p>
      <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-3">
        <Button size="sm" variant="secondary" icon={CheckSquare} onClick={onTask}>{t('Поставить задачу')}</Button>
        <Button size="sm" variant="ghost" icon={X} onClick={onDismiss}>{t('Не актуально')}</Button>
      </div>
    </Card>
  )
}

const TASK_TYPES = [
  ['other', 'Другое'],
  ['retention', 'Вернуть клиента'],
  ['renewal_offer', 'Предложить продление'],
  ['call_back', 'Перезвонить'],
]

function localDueValue() {
  const now = new Date()
  const date = new Date(now.getTime() + 4 * 60 * 60 * 1000)
  if (date.toDateString() !== now.toDateString()) date.setTime(now.getTime() + 15 * 60 * 1000)
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60 * 1000)
  return local.toISOString().slice(0, 16)
}

function DigestTaskModal({ digestId, item, onClose }) {
  const toast = useToast()
  const [taskType, setTaskType] = useState('other')
  const [dueAt, setDueAt] = useState(localDueValue)
  const [assigneeId, setAssigneeId] = useState('')
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    let active = true
    setPreview(null)
    setError('')
    api.post(`ai/digests/${digestId}/task-preview/`, { item_id: item.id, task_type: taskType })
      .then(res => { if (active) setPreview(res.data) })
      .catch(err => { if (active) setError(apiErrorMessage(err)) })
    return () => { active = false }
  }, [digestId, item.id, taskType])

  async function create() {
    setCreating(true)
    try {
      const result = await api.post(`ai/digests/${digestId}/tasks/`, {
        item_id: item.id,
        task_type: taskType,
        due_at: new Date(dueAt).toISOString(),
        assignee_id: assigneeId || null,
      })
      toast.success(t('Создано задач: {n}', { n: result.data.created }))
      onClose()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setCreating(false)
    }
  }

  return (
    <Modal open onClose={onClose} title={t('Поставить задачу')}>
      <p className="mb-4 text-sm text-ink-muted">{item.title}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t('Тип задачи')}>
          {({ id }) => (
            <Select id={id} value={taskType} onChange={event => setTaskType(event.target.value)}>
              {TASK_TYPES.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Срок')}>
          {({ id }) => <Input id={id} type="datetime-local" value={dueAt} onChange={event => setDueAt(event.target.value)} />}
        </Field>
      </div>
      <Field label={t('Исполнитель')} className="mt-3">
        {({ id }) => (
          <Select id={id} value={assigneeId} onChange={event => setAssigneeId(event.target.value)}>
            <option value="">{t('По умолчанию — администратор филиала')}</option>
            {(preview?.assignees || []).map(user => <option key={user.id} value={user.id}>{user.name}</option>)}
          </Select>
        )}
      </Field>

      <div className="mt-4 rounded-xl bg-surface-muted p-3">
        {!preview && !error && <p className="text-sm text-ink-muted">{t('Собираем предпросмотр…')}</p>}
        {error && <p className="text-sm text-danger-600">{error}</p>}
        {preview && (
          <>
            <p className="text-sm font-semibold text-ink">
              {t('Будет создано задач: {n}', { n: preview.new_count })}
            </p>
            {preview.items.some(row => row.already_exists) && (
              <p className="mt-1 text-xs text-ink-muted">{t('Дубликаты пропущены автоматически.')}</p>
            )}
            <ul className="mt-2 max-h-52 space-y-2 overflow-auto">
              {preview.items.slice(0, 20).map((row, index) => (
                <li key={row.child_id || index} className="flex items-start justify-between gap-3 text-[13px]">
                  <span className="min-w-0">
                    <strong className="block truncate text-ink">{row.child_name || item.title}</strong>
                    <span className="text-ink-muted">{row.reason}</span>
                  </span>
                  <span className="shrink-0 text-ink-muted">{row.already_exists ? t('Уже есть') : row.assignee_name}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>{t('Отмена')}</Button>
        <Button loading={creating} disabled={!preview?.new_count || !dueAt} onClick={create}>
          {t('Создать задачи')}
        </Button>
      </div>
    </Modal>
  )
}

function Archive({ items, activeId, onOpen }) {
  if (items.length < 2) return null
  return (
    <Card>
      <CardHeader title={t('Прошлые недели')} description={t('Что советовали раньше — видно, что сработало.')} />
      <ul className="divide-y divide-line">
        {items.map(item => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onOpen(item.id)}
              className={cn('flex w-full items-center gap-3 py-3 text-left', item.id === activeId && 'font-semibold')}
            >
              <History className="size-4 shrink-0 text-ink-subtle" />
              <span className="min-w-0 flex-1 text-sm text-ink">
                {t('Неделя с {date}', { date: dayMonth(item.week_start) })}
                <span className="ml-2 text-[13px] font-normal text-ink-muted">
                  {item.unchanged ? t('без изменений') : `${item.highlights} ${plural(item.highlights, ['главный совет', 'главных совета', 'главных советов'])}`}
                </span>
              </span>
              <ChevronRight className="size-4 text-ink-subtle" />
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
