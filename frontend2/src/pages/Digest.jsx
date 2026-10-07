import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowRight, CalendarClock, ChevronRight, History, Loader2, Newspaper, RefreshCw, Sprout, TrendingDown, TrendingUp } from 'lucide-react'
import api from '../api/axios'
import { AIBadge } from '../components/ai/ai'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Skeleton, apiErrorMessage, cn, formatDateTime, useToast } from '../ui'
import { locale, plural, t } from '../i18n'

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
  // «%» уже стоит у самой цифры.
  return text.replace(/, %$/, '')
}

export default function Digest() {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const selectedId = params.get('id')
  const [data, setData] = useState(null)
  // Выпуск из архива: держим вместе с id, чтобы не показывать чужой при переключении.
  const [loaded, setLoaded] = useState(null)
  const [error, setError] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const load = useCallback(() => api.get('ai/digests/').then(res => { setData(res.data); setError(false) }).catch(() => setError(true)), [])
  useEffect(() => { load() }, [load])

  // Собирается — опрашиваем, пока не будет готов.
  useEffect(() => {
    if (!data?.building) return undefined
    const timer = setInterval(load, POLL_MS)
    return () => clearInterval(timer)
  }, [data?.building, load])

  useEffect(() => {
    if (!selectedId) return
    api.get(`ai/digests/${selectedId}/`).then(res => setLoaded(res.data)).catch(() => setParams({}))
  }, [selectedId, setParams])
  const selected = selectedId && loaded?.id === selectedId ? loaded : null

  async function refresh() {
    setRefreshing(true)
    try {
      const res = await api.post('ai/digests/')
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
  const rest = content.items.filter(item => !content.highlights.some(h => h.id === item.id))
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
          {content.highlights.map(item => <Advice key={item.id} item={item} />)}
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
              </li>
            ))}
          </ul>
        </Card>
      )}
      {content.failed_blocks > 0 && (
        <p className="px-1 text-[13px] text-ink-muted">{t('Часть блоков не собралась — в следующий раз попробуем снова.')}</p>
      )}
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

function Advice({ item }) {
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
    </Card>
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
