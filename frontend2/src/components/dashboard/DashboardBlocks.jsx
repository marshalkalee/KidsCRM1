import { Link } from 'react-router-dom'
import { Cake, CalendarDays, CheckCircle2 } from 'lucide-react'
import { useSession } from '../../session/SessionContext'
import { Button, Card, Skeleton, cn, money, plural } from '../../ui'
import { locale, t } from '../../i18n'
import { Change } from '../analytics'

/*
 * Блоки главной (вариант A пробника): ключевые цифры, «Требует внимания»,
 * продления, дни рождения, занятия на сегодня. Данные — useDashboardData.
 */

const CAPTION = 'font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle'

function BlockTitle({ children, to, link }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-3">
      <h2 className="text-base font-bold text-ink">{children}</h2>
      {to && <Link to={to} className="text-[13px] font-semibold text-brand-700 hover:text-brand-600">{link}</Link>}
    </div>
  )
}

function Tile({ label, value, hint, tone, progress, change, to }) {
  const body = (
    <Card className={cn('h-full px-4 py-4 sm:px-5 sm:py-[18px]', to && 'transition-shadow hover:shadow-pop')}>
      <p className="text-[13px] text-ink-muted">{label}</p>
      <p className={cn('mt-1.5 text-[20px] font-bold leading-tight sm:text-[28px]', tone || 'text-ink')}>{value}</p>
      {change && <div className="mt-1.5">{change}</div>}
      {progress != null && (
        <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-[#f3eef6]">
          <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, progress)}%` }} />
        </div>
      )}
      {hint && <p className="mt-1.5 text-[12px] text-ink-muted sm:text-[12.5px]">{hint}</p>}
    </Card>
  )
  return to ? <Link to={to} className="block">{body}</Link> : body
}

// Сумма в подсказке не разрывается: «389 000 ₸» целиком на одной строке.
const nb = value => money(value).replace(/\s/g, '\u00a0')

function timeOf(value) {
  return String(value || '').slice(11, 16)
}

/** Ключевые цифры — набор по правам: выручка только руководителям, долги — тем, кто видит деньги. */
export function KpiTiles({ data }) {
  const { can } = useSession()
  if (!data) {
    return (
      <div className="mb-5 grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        {[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-[118px]" />)}
      </div>
    )
  }
  const tiles = []
  if (data.active != null) {
    tiles.push({
      key: 'children',
      label: t('Активные дети'),
      value: data.active,
      hint: [data.paused ? t('{n} на паузе', { n: data.paused }) : null, data.left ? t('{n} ушли', { n: data.left }) : null].filter(Boolean).join(' · '),
      to: '/children',
    })
  }
  const revenue = data.revenue
  if (revenue?.revenue) {
    tiles.push({
      key: 'revenue',
      label: t('Выручка за 30 дней'),
      value: money(revenue.revenue.value),
      change: <Change metric={revenue.revenue} />,
      hint: revenue.payments_count?.value
        ? `${revenue.payments_count.value} ${plural(revenue.payments_count.value, ['оплата', 'оплаты', 'оплат'])} · ${t('средний чек {sum}', { sum: nb(revenue.average_check?.value) })}`
        : t('Оплат за 30 дней не было'),
      to: '/analytics/revenue',
    })
  } else if (data.lessons) {
    const teachers = new Set(data.lessons.map(l => l.teacher_name).filter(Boolean))
    const starts = data.lessons.map(l => timeOf(l.starts_at_local)).filter(Boolean).sort()
    const ends = data.lessons.map(l => timeOf(l.ends_at_local)).filter(Boolean).sort()
    tiles.push({
      key: 'lessons',
      label: t('Занятий сегодня'),
      value: data.lessons.length,
      hint: data.lessons.length
        ? t('с {from} до {to} · педагогов: {n}', { from: starts[0], to: ends[ends.length - 1], n: teachers.size })
        : t('Сегодня занятий нет'),
      to: '/schedule',
    })
  }
  if (can('can_view_client_money') && data.debts) {
    const owes = Number(data.debts.total_debt) > 0
    tiles.push({
      key: 'debts',
      label: t('Долги'),
      value: money(data.debts.total_debt),
      tone: owes ? 'text-danger-600' : 'text-success-600',
      hint: owes
        ? t('должников: {n} · просрочено {sum}', { n: data.debts.count, sum: nb(data.debts.overdue_debt) })
        : t('Все оплатили'),
      to: '/money?tab=debts',
    })
  }
  const groups = data.groups?.results
  if (groups?.length) {
    const fill = Math.round(groups.reduce((sum, g) => sum + (g.fill_percent || 0), 0) / groups.length)
    const under = groups.filter(g => g.is_underfilled).length
    tiles.push({
      key: 'groups',
      label: t('Заполненность групп'),
      value: `${fill}%`,
      progress: fill,
      hint: under ? t('групп: {n} · недозаполнены: {u}', { n: groups.length, u: under }) : t('групп: {n}', { n: groups.length }),
      to: '/groups',
    })
  }
  return (
    <div className={cn('mb-5 grid grid-cols-2 gap-3 sm:gap-4', tiles.length >= 4 ? 'xl:grid-cols-4' : 'xl:grid-cols-3', tiles.length === 3 && '[&>*:last-child]:col-span-2 xl:[&>*:last-child]:col-span-1')}>
      {tiles.map(({ key, ...tile }) => <Tile key={key} {...tile} />)}
    </div>
  )
}

// Что требует внимания — из уведомлений (notifications.collect): та же
// очерёдность и те же цифры, что в колокольчике.
const ATTENTION = {
  overdue_debts: {
    tone: 'bg-danger-50 text-danger-600',
    get title() { return t('Просроченные долги') },
    hint: i => (i.total ? t('{sum} · старше {days} дней', { sum: nb(i.total), days: i.days }) : ''),
    get action() { return t('Напомнить') },
  },
  new_leads: {
    tone: 'bg-warning-50 text-warning-600',
    get title() { return t('Новые заявки ждут звонка') },
    hint: () => '',
    get action() { return t('Позвонить') },
  },
  unmarked_lessons: {
    tone: 'bg-info-50 text-info-600',
    get title() { return t('Вчерашние занятия без отметки') },
    hint: i => (i.date ? new Date(i.date).toLocaleDateString(locale, { day: 'numeric', month: 'long' }) : ''),
    get action() { return t('Отметить') },
  },
  no_subscription: {
    tone: 'bg-[#f3eef6] text-ink-muted',
    get title() { return t('Ходят без абонемента') },
    hint: () => t('продать абонемент'),
    get action() { return t('Список') },
  },
  overdue_tasks: {
    tone: 'bg-[#f3eef6] text-ink-muted',
    get title() { return t('Просроченные задачи') },
    hint: () => '',
    get action() { return t('Открыть') },
  },
}
const ATTENTION_ORDER = ['overdue_debts', 'new_leads', 'unmarked_lessons', 'no_subscription', 'overdue_tasks']

export function Attention({ items }) {
  if (items === undefined) return null
  if (!items) return <Skeleton className="h-72" />
  const rows = ATTENTION_ORDER
    .map(kind => items.find(i => i.kind === kind && i.available && i.count))
    .filter(Boolean)
  return (
    <Card>
      <BlockTitle>{t('Требует внимания')}</BlockTitle>
      {rows.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <CheckCircle2 className="size-9 text-success-600" />
          <p className="font-semibold text-ink">{t('Срочных дел нет')}</p>
          <p className="text-sm text-ink-muted">{t('Долги, заявки и посещаемость в порядке.')}</p>
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map(item => {
            const meta = ATTENTION[item.kind]
            const hint = meta.hint(item)
            return (
              <li key={item.kind} className="flex items-center gap-3.5 py-3 first:pt-1 last:pb-0">
                <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-[10px] text-[15px] font-bold', meta.tone)}>{item.count}</span>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink">{meta.title}</p>
                  {hint && <p className="text-[12.5px] text-ink-muted">{hint}</p>}
                </div>
                <Button to={item.link} size="sm">{meta.action}</Button>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function renewalStatus(row) {
  const left = row.sessions_remaining != null ? ` · ${t('осталось занятий: {n}', { n: row.sessions_remaining })}` : ''
  if (row.days_left < 0) {
    return { text: (row.days_left === -1 ? t('истёк вчера') : t('истёк {n} дн. назад', { n: -row.days_left })) + left, tone: 'text-danger-600' }
  }
  if (row.days_left === 0) return { text: t('заканчивается сегодня') + left, tone: 'text-warning-600' }
  return { text: t('через {n} дн.', { n: row.days_left }) + left, tone: row.days_left <= 3 ? 'text-warning-600' : 'text-ink-muted' }
}

/** data: null — грузится, undefined — нет прав или не загрузилось. */
export function Renewals({ data }) {
  if (data === undefined) return null
  if (!data) return <Skeleton className="h-40" />
  return (
    <Card>
      <BlockTitle to="/money?tab=renewals" link={data.count ? t('Все {n}', { n: data.count }) : null}>{t('Продления')}</BlockTitle>
      {data.results.length === 0 ? (
        <p className="py-3 text-sm text-ink-muted">{t('Ближайших продлений нет.')}</p>
      ) : (
        <ul className="divide-y divide-line">
          {data.results.slice(0, 4).map(row => {
            const status = renewalStatus(row)
            return (
              <li key={row.subscription_id} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 py-2.5">
                <Link to={`/children/${row.child_id}`} className="font-semibold text-ink hover:text-brand-700">{row.child_name}</Link>
                <span className={cn('text-[13px]', status.tone)}>{status.text}</span>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

const age = n => `${n} ${plural(n, ['год', 'года', 'лет'])}`

export function Birthdays({ rows }) {
  if (rows === undefined) return null
  if (!rows) return <Skeleton className="h-32" />
  return (
    <Card>
      <BlockTitle>{t('Дни рождения')}</BlockTitle>
      {rows.length === 0 ? (
        <p className="flex items-center gap-2 py-3 text-sm text-ink-muted"><Cake className="size-4" /> {t('На этой неделе дней рождения нет.')}</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.slice(0, 5).map(row => (
            <li key={row.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2.5">
              <Link to={`/children/${row.id}`} className="font-semibold text-ink hover:text-brand-700">{row.full_name}</Link>
              <span className={cn('text-[13px]', row.days_until === 0 ? 'font-semibold text-brand-700' : 'text-ink-muted')}>
                {row.days_until === 0
                  ? `${t('сегодня')} · ${age(row.turns)}`
                  : `${row.days_until === 1 ? t('завтра') : new Date(row.date).toLocaleDateString(locale, { day: 'numeric', month: 'long' })} · ${age(row.turns)}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

const LESSONS_SHOWN = 8

/** Занятия на сегодня — по времени начала, слоты рядом (до 8 занятий). */
export function TodayLessons({ lessons, mine }) {
  if (lessons === undefined) return null
  if (!lessons) return <Skeleton className="h-56" />
  const shown = lessons
    .filter(l => l.status !== 'cancelled')
    .sort((a, b) => String(a.starts_at_local).localeCompare(String(b.starts_at_local)))
  const slots = []
  for (const lesson of shown.slice(0, LESSONS_SHOWN)) {
    const key = `${timeOf(lesson.starts_at_local)} — ${timeOf(lesson.ends_at_local)}`
    const slot = slots.find(s => s.key === key)
    if (slot) slot.lessons.push(lesson)
    else slots.push({ key, lessons: [lesson] })
  }
  const cancelled = lessons.length - shown.length
  return (
    <Card className="mb-6">
      <BlockTitle to="/schedule" link={t('Расписание')}>
        {mine ? t('Мои занятия сегодня') : t('Занятия сегодня')}{shown.length ? ` · ${shown.length}` : ''}
      </BlockTitle>
      {shown.length === 0 ? (
        <p className="flex items-center gap-2 py-4 text-sm text-ink-muted"><CalendarDays className="size-4" /> {t('Сегодня занятий нет.')}</p>
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          {slots.map(slot => (
            <div key={slot.key} className="flex flex-col gap-2">
              <p className={CAPTION}>{slot.key}</p>
              {slot.lessons.map(lesson => {
                const name = lesson.group_name || (lesson.individual_children_names || []).join(', ') || t('Индивидуальное')
                return (
                  <div key={lesson.id} className="flex items-center justify-between gap-3 rounded-[10px] border border-line px-3 py-2.5">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-ink">{name}</p>
                      <p className="truncate text-[13px] text-ink-muted">{[lesson.teacher_name, lesson.room_name].filter(Boolean).join(' · ')}</p>
                    </div>
                    <span className="shrink-0 text-[13px] text-ink-muted">
                      {lesson.capacity ? t('{n} из {c}', { n: lesson.total_participants_count ?? 0, c: lesson.capacity }) : lesson.total_participants_count}
                    </span>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
      {(shown.length > LESSONS_SHOWN || cancelled > 0) && (
        <p className="mt-3 text-[13px] text-ink-muted">
          {[shown.length > LESSONS_SHOWN ? t('ещё занятий: {n}', { n: shown.length - LESSONS_SHOWN }) : null, cancelled ? t('отменено: {n}', { n: cancelled }) : null].filter(Boolean).join(' · ')}
          {' '}<Link to="/schedule" className="font-semibold text-brand-700">{t('Открыть расписание')}</Link>
        </p>
      )}
    </Card>
  )
}
