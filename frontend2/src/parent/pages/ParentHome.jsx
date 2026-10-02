import { Link } from 'react-router-dom'
import { ArrowRight, CalendarDays, Clock, MapPin, Snowflake, UserRound, Wallet } from 'lucide-react'
import { Card, ErrorState, Skeleton, cn, money, plural } from '../../ui'
import { locale, t } from '../../i18n'
import { usePortalData } from '../api'
import { useParent } from '../useParent'

/*
 * Главный экран кабинета (TRU-138): когда следующее занятие, сколько
 * осталось занятий, сколько к оплате — без нажатий.
 *
 * Тон — для клиента: «к оплате», а не «задолженность»; «осталось 2
 * занятия — можно продлить», а не предупреждение. Цифры приходят с
 * сервера из тех же сервисов, что у администратора (portal/summary.py).
 * Время занятий — время центра (строка с часовым поясом центра).
 */

const centerTime = iso => iso.slice(11, 16)
const centerDate = iso => iso.slice(0, 10)

function dayLabel(isoDate, today) {
  const date = new Date(`${isoDate}T12:00:00`)
  const base = new Date(`${today}T12:00:00`)
  const diff = Math.round((date - base) / 86400000)
  const full = date.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' })
  if (diff === 0) return t('Сегодня, {date}', { date: date.toLocaleDateString(locale, { day: 'numeric', month: 'long' }) })
  if (diff === 1) return t('Завтра, {date}', { date: date.toLocaleDateString(locale, { day: 'numeric', month: 'long' }) })
  return full.charAt(0).toUpperCase() + full.slice(1)
}

function shortDate(iso) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'long' })
}

export default function ParentHome() {
  const { child } = useParent()
  const { data, loading, reload } = usePortalData(child && `children/${child.id}/summary/`)

  if (!child) return null
  if (!data && loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-44" />
        <Skeleton className="h-32" />
        <Skeleton className="h-24" />
      </div>
    )
  }
  if (!data) return <Card><ErrorState onRetry={reload} /></Card>

  return (
    <div className="space-y-3">
      <NextLesson lessons={data.next_lessons} today={data.today} left={child.status === 'left'} />
      <SubscriptionCard subscription={data.subscription} />
      <ToPay amount={Number(data.to_pay)} kaspi={data.payment?.kaspi} />
    </div>
  )
}

function NextLesson({ lessons, today, left }) {
  const [next, ...later] = lessons
  if (!next) {
    return (
      <Card className="flex items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface-muted text-ink-muted"><CalendarDays className="size-5" /></span>
        <p className="text-sm text-ink-muted">{left ? t('Ребёнок сейчас не ходит в центр.') : t('Ближайших занятий в расписании нет.')}</p>
      </Card>
    )
  }
  return (
    <Card padded={false} className="overflow-hidden">
      <div className="bg-[linear-gradient(135deg,#fff1ee,#ffe4ea)] px-5 py-4">
        <p className="font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-brand-700">{t('Следующее занятие')}</p>
        <p className="mt-1 text-[20px] font-bold leading-tight text-ink">{dayLabel(centerDate(next.starts_at), today)}</p>
        <p className="mt-0.5 flex items-center gap-1.5 text-[17px] font-semibold text-ink">
          <Clock className="size-4 text-brand-600" /> {centerTime(next.starts_at)}–{centerTime(next.ends_at)}
        </p>
      </div>
      <div className="space-y-1.5 px-5 py-4 text-sm">
        <p className="font-semibold text-ink">
          {next.group || t('Индивидуальное занятие')}
          {next.kind === 'trial' && <span className="ml-2 rounded-full bg-info-50 px-2 py-0.5 text-[11px] font-semibold text-info-600">{t('пробное')}</span>}
          {next.kind === 'makeup' && <span className="ml-2 rounded-full bg-info-50 px-2 py-0.5 text-[11px] font-semibold text-info-600">{t('отработка')}</span>}
        </p>
        {(next.branch || next.room) && (
          <p className="flex items-start gap-1.5 text-ink-muted">
            <MapPin className="mt-0.5 size-4 shrink-0" />
            <span>{[next.branch, next.address, next.room].filter(Boolean).join(' · ')}</span>
          </p>
        )}
        {next.teacher && <p className="flex items-center gap-1.5 text-ink-muted"><UserRound className="size-4 shrink-0" />{next.teacher}</p>}
      </div>
      {later.length > 0 && (
        <div className="border-t border-line px-5 py-3">
          <p className="text-[12.5px] text-ink-muted">
            {t('Дальше')}: {later.map(l => `${shortDate(centerDate(l.starts_at))}, ${centerTime(l.starts_at)}`).join(' · ')}
          </p>
          <Link to="/parent/schedule" className="mt-1 inline-flex items-center gap-1 text-[13px] font-semibold text-brand-700">
            {t('Всё расписание')} <ArrowRight className="size-3.5" />
          </Link>
        </div>
      )}
    </Card>
  )
}

function SubscriptionCard({ subscription: s }) {
  if (!s) {
    return (
      <Card>
        <p className="font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Абонемент')}</p>
        <p className="mt-1 text-sm text-ink-muted">{t('Действующего абонемента нет. Администратор центра подскажет, какой подойдёт.')}</p>
      </Card>
    )
  }
  const active = s.status === 'active' || s.status === 'frozen'
  const used = s.sessions_total ? s.sessions_total - (s.sessions_remaining ?? 0) : 0
  return (
    <Link to="/parent/subscription" className="block">
      <Card className="transition-shadow hover:shadow-pop">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Абонемент')}</p>
            <p className="mt-1 font-semibold text-ink">{s.name}</p>
          </div>
          <ArrowRight className="mt-1 size-4 shrink-0 text-ink-subtle" />
        </div>

        {active && !s.is_unlimited && s.sessions_remaining != null && (
          <>
            <p className="mt-2 text-[22px] font-bold leading-tight text-ink">
              {t('Осталось {n} из {total}', { n: s.sessions_remaining, total: s.sessions_total })}
              <span className="ml-1.5 text-sm font-normal text-ink-muted">{plural(s.sessions_total, ['занятия', 'занятий', 'занятий'])}</span>
            </p>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(0, Math.min(100, ((s.sessions_total - used) / s.sessions_total) * 100))}%` }} />
            </div>
          </>
        )}
        {active && s.is_unlimited && <p className="mt-2 text-[17px] font-semibold text-ink">{t('Без ограничения по занятиям')}</p>}

        <p className="mt-2 text-sm text-ink-muted">
          {s.status === 'frozen' && s.freeze
            ? <span className="inline-flex items-center gap-1.5"><Snowflake className="size-4 text-info-600" />{s.freeze.ends_on ? t('Заморожен до {date}', { date: shortDate(s.freeze.ends_on) }) : t('Заморожен')}</span>
            : active
              ? t('Действует до {date}', { date: shortDate(s.ends_on) })
              : t('Закончился {date}', { date: shortDate(s.ends_on) })}
        </p>
        {s.ending_soon && (
          <p className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-[13px] text-brand-700">
            {s.is_unlimited || s.sessions_remaining == null
              ? t('Абонемент скоро закончится — можно продлить у администратора.')
              : t('Осталось {n} {word} — можно продлить у администратора.', { n: s.sessions_remaining, word: plural(s.sessions_remaining, ['занятие', 'занятия', 'занятий']) })}
          </p>
        )}
        {!active && <p className="mt-3 rounded-lg bg-surface-muted px-3 py-2 text-[13px] text-ink-muted">{t('Чтобы продолжить занятия, продлите абонемент у администратора.')}</p>}
      </Card>
    </Link>
  )
}

function ToPay({ amount, kaspi }) {
  if (!(amount > 0)) {
    return (
      <Card className="flex items-center gap-3 py-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-success-50 text-success-600"><Wallet className="size-4" /></span>
        <p className="text-sm font-semibold text-success-600">{t('Всё оплачено')}</p>
      </Card>
    )
  }
  const isLink = /^https?:\/\//.test(kaspi || '')
  return (
    <Card>
      <p className="font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('К оплате')}</p>
      <p className="mt-1 text-[22px] font-bold text-ink">{money(amount)}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {isLink && (
          <a href={kaspi} target="_blank" rel="noreferrer" className={cn('inline-flex h-10 items-center rounded-md bg-[#f14635] px-4 text-sm font-semibold text-white hover:brightness-95')}>
            {t('Оплатить через Kaspi')}
          </a>
        )}
        <Link to="/parent/subscription" className="inline-flex h-10 items-center rounded-md border border-line-strong px-4 text-sm font-semibold text-ink">
          {t('Подробнее')}
        </Link>
      </div>
      {kaspi && !isLink && <p className="mt-2 text-[13px] text-ink-muted">{t('Перевод через Kaspi: {details}', { details: kaspi })}</p>}
    </Card>
  )
}
