import { useState } from 'react'
import { MessageCircle, Phone, Snowflake, Wallet } from 'lucide-react'
import { Card, CardHeader, ErrorState, Skeleton, cn, formatPhone, money, plural } from '../../ui'
import { locale, t } from '../../i18n'
import { usePortalData } from '../api'
import { useParent } from '../useParent'

/*
 * Абонемент и оплаты в кабинете (TRU-139), только просмотр.
 * Остаток объясняется журналом: какое занятие списалось и когда — тот же
 * журнал, что у администратора (portal/money.py). Онлайн-оплаты нет
 * (ТЗ п. 12): вместо кнопки «оплатить» — реквизиты Kaspi и телефон
 * филиала с WhatsApp, чтобы не пришлось звонить и спрашивать.
 */

const SHOWN_ENTRIES = 6

const dateOf = iso => new Date(`${iso.slice(0, 10)}T12:00:00`)
const shortDate = iso => dateOf(iso).toLocaleDateString(locale, { day: 'numeric', month: 'long' })
const dayWithWeekday = iso => dateOf(iso).toLocaleDateString(locale, { weekday: 'short', day: 'numeric', month: 'short' })

const STATUS = {
  active: { get label() { return t('Действует') }, tone: 'bg-success-50 text-success-600' },
  frozen: { get label() { return t('Заморожен') }, tone: 'bg-info-50 text-info-600' },
  expired: { get label() { return t('Закончился') }, tone: 'bg-surface-muted text-ink-muted' },
  exhausted: { get label() { return t('Занятия закончились') }, tone: 'bg-surface-muted text-ink-muted' },
}

export default function ParentSubscription() {
  const { child } = useParent()
  const { data, loading, reload } = usePortalData(child && `children/${child.id}/money/`)
  if (!child) return null
  if (!data && loading) return <div className="space-y-3"><Skeleton className="h-48" /><Skeleton className="h-40" /></div>
  if (!data) return <Card><ErrorState onRetry={reload} /></Card>

  return (
    <div className="space-y-3">
      <Current subscription={data.current} />
      <HowToPay amount={Number(data.to_pay)} howToPay={data.how_to_pay} />
      {data.current && data.ledger.length > 0 && <Ledger entries={data.ledger} unlimited={data.current.is_unlimited} />}
      <Payments rows={data.payments} />
      {data.history.length > 0 && <History rows={data.history} />}
    </div>
  )
}

function Current({ subscription: s }) {
  if (!s) {
    return (
      <Card>
        <CardHeader title={t('Абонемент')} />
        <p className="text-sm text-ink-muted">{t('Действующего абонемента нет. Администратор центра подскажет, какой подойдёт.')}</p>
      </Card>
    )
  }
  const status = STATUS[s.status] || STATUS.expired
  const active = s.status === 'active' || s.status === 'frozen'
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-lg font-bold text-ink">{s.name}</p>
          <p className="text-[13px] text-ink-muted">{[s.direction, `${shortDate(s.starts_on)} — ${shortDate(s.ends_on)}`].filter(Boolean).join(' · ')}</p>
        </div>
        <span className={cn('shrink-0 rounded-full px-2.5 py-0.5 text-[12px] font-semibold', status.tone)}>{status.label}</span>
      </div>

      {!active ? null : s.is_unlimited ? (
        <p className="mt-3 text-[17px] font-semibold text-ink">{t('Без ограничения по занятиям')}</p>
      ) : s.sessions_remaining != null && (
        <>
          <p className="mt-3 text-[28px] font-bold leading-none text-ink">
            {s.sessions_remaining}
            <span className="ml-2 text-sm font-normal text-ink-muted">{t('из {total} {word} осталось', { total: s.sessions_total, word: plural(s.sessions_total, ['занятия', 'занятий', 'занятий']) })}</span>
          </p>
          <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-surface-muted">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(0, Math.min(100, (s.sessions_remaining / s.sessions_total) * 100))}%` }} />
          </div>
        </>
      )}

      {s.status === 'frozen' && s.freeze && (
        <p className="mt-3 flex items-start gap-2 rounded-lg bg-info-50 px-3 py-2 text-[13px] text-info-600">
          <Snowflake className="mt-0.5 size-4 shrink-0" />
          {s.freeze.ends_on
            ? t('Заморожен с {from} по {to}. Абонемент продлится до {end}.', { from: shortDate(s.freeze.starts_on), to: shortDate(s.freeze.ends_on), end: shortDate(s.ends_on) })
            : t('Заморожен с {from}.', { from: shortDate(s.freeze.starts_on) })}
        </p>
      )}
      {s.ending_soon && (
        <p className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-[13px] text-brand-700">
          {s.is_unlimited || s.sessions_remaining == null
            ? t('Абонемент действует до {date} — можно продлить у администратора.', { date: shortDate(s.ends_on) })
            : t('Осталось {n} {word} — можно продлить у администратора.', { n: s.sessions_remaining, word: plural(s.sessions_remaining, ['занятие', 'занятия', 'занятий']) })}
        </p>
      )}
      {!active && <p className="mt-3 rounded-lg bg-surface-muted px-3 py-2 text-[13px] text-ink-muted">{t('Чтобы продолжить занятия, продлите абонемент у администратора.')}</p>}
    </Card>
  )
}

function HowToPay({ amount, howToPay }) {
  const contacts = howToPay?.contacts || []
  return (
    <Card>
      {amount > 0 ? (
        <>
          <p className="font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('К оплате')}</p>
          <p className="mt-1 text-[24px] font-bold text-ink">{money(amount)}</p>
        </>
      ) : (
        <p className="flex items-center gap-2 font-semibold text-success-600"><Wallet className="size-4" /> {t('Всё оплачено')}</p>
      )}
      {amount > 0 && (
        <div className="mt-3 space-y-2 border-t border-line pt-3">
          <p className="text-[13px] font-semibold text-ink">{t('Как оплатить')}</p>
          <p className="text-[13px] text-ink-muted">{t('Оплатить можно в центре или переводом — уточните у администратора.')}</p>
          {contacts.map(c => (
            <div key={c.phone} className="flex flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 text-sm text-ink">{c.branch} · {formatPhone(c.phone)}</span>
              <a href={c.whatsapp_url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-1.5 rounded-md bg-success-600 px-3 text-[13px] font-semibold text-white">
                <MessageCircle className="size-4" /> WhatsApp
              </a>
              <a href={`tel:${c.phone}`} aria-label={t('Позвонить')} className="inline-flex size-9 items-center justify-center rounded-md border border-line-strong text-ink">
                <Phone className="size-4" />
              </a>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function Ledger({ entries, unlimited }) {
  const [all, setAll] = useState(false)
  const shown = all ? entries : entries.slice(0, SHOWN_ENTRIES)
  return (
    <Card>
      <CardHeader
        title={unlimited ? t('Посещения по абонементу') : t('Из чего сложился остаток')}
        description={unlimited ? null : t('Каждое посещённое занятие списывает одно занятие с абонемента.')}
      />
      <ul className="divide-y divide-line">
        {shown.map((row, i) => {
          const when = row.lesson ? `${dayWithWeekday(row.lesson.starts_at)}, ${row.lesson.starts_at.slice(11, 16)}` : shortDate(row.date)
          return (
            <li key={i} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className={cn('text-sm font-semibold', row.reverted ? 'text-ink-subtle line-through' : 'text-ink')}>
                  {t(row.label)}{row.lesson?.group ? ` · ${row.lesson.group}` : ''}
                </p>
                <p className="text-[12.5px] text-ink-muted">{when}{row.reverted ? ` · ${t('отменено')}` : ''}</p>
              </div>
              {!unlimited && (
                <div className="shrink-0 text-right">
                  <p className={cn('text-sm font-bold', row.delta > 0 ? 'text-success-600' : 'text-ink')}>{row.delta > 0 ? `+${row.delta}` : row.delta}</p>
                  <p className="text-[11.5px] text-ink-subtle">{t('осталось {n}', { n: row.balance })}</p>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {entries.length > SHOWN_ENTRIES && (
        <button type="button" onClick={() => setAll(v => !v)} className="mt-3 text-[13px] font-semibold text-brand-700">
          {all ? t('Свернуть') : t('Показать все ({n})', { n: entries.length })}
        </button>
      )}
    </Card>
  )
}

function Payments({ rows }) {
  return (
    <Card>
      <CardHeader title={t('Оплаты')} />
      {rows.length === 0 ? (
        <p className="text-sm text-ink-muted">{t('Оплат пока нет.')}</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map(p => (
            <li key={p.id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">{p.subscription}</p>
                <p className="text-[12.5px] text-ink-muted">{shortDate(p.paid_at)} · {t(p.method_display)}</p>
              </div>
              <p className="shrink-0 font-bold text-ink">{money(p.amount)}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function History({ rows }) {
  return (
    <Card>
      <CardHeader title={t('Прошлые абонементы')} />
      <ul className="divide-y divide-line">
        {rows.map(s => (
          <li key={s.id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">{s.name}</p>
              <p className="text-[12.5px] text-ink-muted">{shortDate(s.starts_on)} — {shortDate(s.ends_on)}</p>
            </div>
            <p className="shrink-0 text-sm text-ink">{money(s.price)}</p>
          </li>
        ))}
      </ul>
    </Card>
  )
}
