import { useEffect, useRef, useState } from 'react'
import { FileText, Megaphone } from 'lucide-react'
import { Card, EmptyState, ErrorState, Skeleton, cn } from '../../ui'
import { locale, t } from '../../i18n'
import portal, { usePortalData } from '../api'

/*
 * Объявления центра в кабинете (TRU-140): актуальные сверху, архив
 * истёкших. Открыл ленту — непрочитанные отмечаются прочитанными.
 */

const isImage = url => /\.(jpe?g|png|webp)$/i.test(url || '')

function published(iso) {
  return new Date(iso).toLocaleDateString(locale, { day: 'numeric', month: 'long' })
}

export default function ParentNews() {
  const [archive, setArchive] = useState(false)
  const { data, loading, reload } = usePortalData(archive ? 'announcements/?archive=1' : 'announcements/')
  // Какие были новыми при открытии: метка «новое» держится до следующего
  // захода, даже когда сервер уже ответил «прочитано».
  const [fresh, setFresh] = useState(() => new Set())
  const seen = useRef(new Set())
  const unreadNow = (data?.results || []).filter(r => !r.read && !fresh.has(r.id))
  if (unreadNow.length) setFresh(new Set([...fresh, ...unreadNow.map(r => r.id)]))

  // Показали — значит прочитали. Метка «новое» остаётся до следующего захода.
  useEffect(() => {
    for (const row of data?.results || []) {
      if (row.read || seen.current.has(row.id)) continue
      seen.current.add(row.id)
      portal.post(`announcements/${row.id}/read/`).catch(() => {})
    }
  }, [data])

  return (
    <div className="space-y-3">
      <div role="tablist" aria-label={t('Объявления')} className="grid grid-cols-2 gap-1 rounded-lg bg-surface p-1 shadow-card">
        {[[false, t('Актуальные')], [true, t('Архив')]].map(([value, label]) => (
          <button
            key={label}
            type="button"
            role="tab"
            aria-selected={archive === value}
            onClick={() => setArchive(value)}
            className={cn('h-9 rounded-md text-sm font-semibold', archive === value ? 'bg-brand-50 text-brand-700' : 'text-ink-muted')}
          >
            {label}
          </button>
        ))}
      </div>

      {!data && loading && <Skeleton className="h-40" />}
      {!data && !loading && <Card><ErrorState onRetry={reload} /></Card>}
      {data?.results.length === 0 && (
        <Card>
          <EmptyState icon={Megaphone} title={archive ? t('Архив пуст') : t('Новых объявлений нет')} description={archive ? null : t('Здесь центр пишет о концертах, праздничном расписании и сборах.')} />
        </Card>
      )}
      {data?.results.map(row => (
        <Card key={row.id} className="space-y-2">
          <div className="flex items-start justify-between gap-3">
            <p className="text-base font-bold text-ink">{row.title}</p>
            {fresh.has(row.id) && <span className="mt-1 shrink-0 rounded-full bg-brand-500 px-2 py-0.5 text-[11px] font-semibold text-white">{t('новое')}</span>}
          </div>
          <p className="text-[12.5px] text-ink-muted">
            {[published(row.published_at), row.organization, row.children.join(', ')].filter(Boolean).join(' · ')}
          </p>
          {row.body && <p className="whitespace-pre-line text-sm leading-relaxed text-ink">{row.body}</p>}
          {row.attachment_url && (isImage(row.attachment_url) ? (
            <a href={row.attachment_url} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border border-line">
              <img src={row.attachment_url} alt={row.attachment_name} className="max-h-96 w-full object-contain" loading="lazy" />
            </a>
          ) : (
            <a href={row.attachment_url} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg border border-line px-3 py-2.5 text-sm font-semibold text-brand-700">
              <FileText className="size-4 shrink-0" /> <span className="truncate">{row.attachment_name || t('Открыть файл')}</span>
            </a>
          ))}
          {row.expires_on && !archive && <p className="text-[12px] text-ink-subtle">{t('Актуально до {date}', { date: published(`${row.expires_on}T12:00:00`) })}</p>}
        </Card>
      ))}
    </div>
  )
}
