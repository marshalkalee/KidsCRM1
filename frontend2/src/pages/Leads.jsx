import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AlarmClock, ArrowRightLeft, Columns3, Inbox, Plus, Search, Table2 } from 'lucide-react'
import api from '../api/axios'
import { LEAD_CREATED_EVENT, openQuickLead } from '../components/leads/QuickLead'
import LeadTable from '../components/leads/LeadTable'
import RejectModal from '../components/leads/RejectModal'
import { STAGE_DOT, leadTitle } from '../components/leads/format'
import { getLeadsViewPreference, setLeadsViewPreference } from '../components/leads/viewPreference'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Button, DateInput, Dropdown, EmptyState, ErrorState, FilterBar, FilterPanel, FilterSelect, PageHeader, SearchInput,
  Skeleton, Tabs, ageLabel, apiErrorMessage, cn, plural, useFilterDraft, useToast,
} from '../ui'
import { t } from '../i18n'

// status — приходит из аналитики (TRU-115, «сейчас на этапе»): в панели его
// поля нет, но он считается фильтром и сбрасывается вместе с остальными.
const FILTER_KEYS = ['source', 'direction', 'branch', 'assigned_to', 'created_from', 'created_to', 'status']
const LIMIT = 20

/**
 * Воронка продаж — kanban (TRU-94). Колонки — этапы центра (TRU-154): их
 * названия, цвета и порядок приходят с сервера, переходы между ними тоже
 * (stage_transitions). Перетаскивание меняет этап (в «Отказ» — только с
 * причиной), «висит N дней» — прямо на карточке. Фильтры в адресе: ими можно
 * поделиться, их же возьмёт таблица (TRU-95). На телефоне — одна колонка с
 * переключателем этапа.
 */
export default function Leads() {
  const toast = useToast()
  const navigate = useNavigate()
  const { branches } = useSession()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const [board, setBoard] = useState(null)
  const [error, setError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [lists, setLists] = useState({ sources: [], directions: [], staff: [] })
  const [rejecting, setRejecting] = useState(null)
  const [mobileStage, setMobileStage] = useState(null)
  const [tableCount, setTableCount] = useState(null)
  // URL сохраняет конкретный возврат с фильтрами, localStorage — ручной
  // выбор пользователя при обычном переходе на /leads без параметров.
  const requestedView = params.get('view')
  const view = ['board', 'table'].includes(requestedView)
    ? requestedView
    : getLeadsViewPreference()
  const returnTo = `${location.pathname}${location.search}`
  // Новые заявки и продления — две воронки, не смешиваются (TRU-98).
  const kind = params.get('kind') === 'renewal' ? 'renewal' : 'new'

  const query = useMemo(() => {
    const q = {}
    for (const key of ['q', 'kind', ...FILTER_KEYS]) if (params.get(key)) q[key] = params.get(key)
    return q
  }, [params])
  const queryKey = JSON.stringify(query)

  const update = useCallback(changes => {
    setParams(current => {
      const next = new URLSearchParams(current)
      Object.entries(changes).forEach(([key, value]) => (value ? next.set(key, value) : next.delete(key)))
      // Поменяли фильтры, поиск или сортировку — таблица с первой страницы.
      if (!('page' in changes)) next.delete('page')
      return next
    }, { replace: true })
  }, [setParams])

  const changeView = useCallback(next => {
    const normalized = next === 'table' ? 'table' : 'board'
    setLeadsViewPreference(normalized)
    update({ view: normalized, page: '' })
  }, [update])

  useEffect(() => {
    // Явный view в ссылке тоже становится последним выбранным видом.
    if (['board', 'table'].includes(requestedView)) setLeadsViewPreference(view)
  }, [requestedView, view])

  useEffect(() => {
    if (view !== 'board') return undefined
    let alive = true
    api.get('leads/board/', { params: { ...JSON.parse(queryKey), limit: LIMIT } })
      .then(res => { if (alive) { setBoard(res.data); setError(false) } })
      .catch(() => { if (alive) setError(true) })
    return () => { alive = false }
  }, [queryKey, reloadKey, view])

  useEffect(() => {
    const reload = () => setReloadKey(k => k + 1)
    window.addEventListener('kc:branch-changed', reload)
    window.addEventListener(LEAD_CREATED_EVENT, reload)
    return () => {
      window.removeEventListener('kc:branch-changed', reload)
      window.removeEventListener(LEAD_CREATED_EVENT, reload)
    }
  }, [])

  useEffect(() => {
    Promise.all([api.get('leads/sources/'), api.get('directions/'), api.get('users/')])
      .then(([s, d, u]) => setLists({
        sources: s.data,
        directions: d.data.results || d.data,
        staff: (u.data.results || u.data).filter(user => ['owner', 'manager', 'admin'].includes(user.role)),
      }))
      .catch(() => {})
  }, [])

  const total = board ? board.columns.reduce((sum, c) => sum + c.count, 0) : 0
  const activeFilters = FILTER_KEYS.filter(key => params.get(key)).length

  const stageOf = id => board?.columns.find(c => c.stage === id)
  const mobileColumn = stageOf(mobileStage) ? mobileStage : board?.columns[0]?.stage

  // Перенос карточки: сразу на доске, откат при ошибке сервера.
  async function move(lead, to, extra = {}) {
    const snapshot = board
    const target = stageOf(to)
    setBoard(current => moveCard(current, lead, target))
    try {
      const res = await api.post(`leads/${lead.id}/status/`, { stage: to, ...extra })
      setBoard(current => replaceCard(current, res.data))
      toast.success(t('«{name}» → {status}', { name: leadTitle(lead), status: target.label }))
      if (target.status === 'trial_attended' && !res.data.converted_child) {
        navigate(`/leads/${lead.id}`, { state: { leadsReturnTo: returnTo } })
      }
    } catch (err) {
      setBoard(snapshot)
      toast.error(apiErrorMessage(err))
    }
  }

  function requestMove(lead, to) {
    if (lead.stage === to) return
    const target = stageOf(to)
    if (!target || !board.stage_transitions[lead.stage]?.includes(to)) {
      toast.error(t('Из статуса «{from}» нельзя перейти в «{to}».', { from: lead.stage_name, to: target?.label ?? '' }))
      return
    }
    if (target.status === 'rejected') setRejecting({ lead, stage: to })
    else move(lead, to)
  }

  async function loadMore(stage) {
    const column = stageOf(stage)
    try {
      const res = await api.get('leads/board/', { params: { ...query, limit: LIMIT, column: stage, offset: column.results.length } })
      const more = res.data.columns[0]
      setBoard(current => ({
        ...current,
        columns: current.columns.map(c => (c.stage === stage ? { ...c, has_more: more.has_more, results: [...c.results, ...more.results] } : c)),
      }))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const resetFilters = () => update(Object.fromEntries(FILTER_KEYS.map(key => [key, ''])))
  const count = view === 'table' ? tableCount : board ? total : null

  return (
    <div>
      <PageHeader
        title={t('Заявки')}
        description={count == null ? t('Загрузка…') : `${count} ${plural(count, ['заявка', 'заявки', 'заявок'])}`}
        actions={
          <>
            <ViewToggle view={view} onChange={changeView} />
            {kind === 'new' && <Button variant="primary" icon={Plus} onClick={openQuickLead}>{t('Новая заявка')}</Button>}
          </>
        }
      />

      <Tabs
        className="mb-4"
        value={kind}
        onChange={next => update({ kind: next === 'renewal' ? 'renewal' : '' })}
        tabs={[{ key: 'new', label: t('Новые заявки') }, { key: 'renewal', label: t('Продления') }]}
      />

      <div className="mb-4 space-y-3">
        <FilterBar
          search={<SearchInput value={params.get('q') || ''} onChange={value => update({ q: value })} placeholder={t('Имя родителя, ребёнка или телефон')} />}
          filtersOpen={filtersOpen}
          onToggleFilters={() => setFiltersOpen(o => !o)}
          activeCount={activeFilters}
        />
        {filtersOpen && <LeadFilters params={params} update={update} lists={lists} branches={branches} onReset={resetFilters} />}
      </div>

      {view === 'table' ? (
        <LeadTable
          query={query}
          params={params}
          update={update}
          reloadKey={reloadKey}
          staff={lists.staff}
          onCount={setTableCount}
          onReset={resetFilters}
          hasFilters={Boolean(activeFilters || params.get('q'))}
          returnTo={returnTo}
        />
      ) : error ? (
        <ErrorState onRetry={() => setReloadKey(k => k + 1)} />
      ) : !board ? (
        <BoardSkeleton />
      ) : total === 0 ? (
        <div className="rounded-xl border border-line bg-surface">
          {activeFilters || params.get('q') ? (
            <EmptyState icon={Search} title={t('Ничего не нашли')} description={t('Попробуйте изменить поиск или сбросить фильтры.')} action={<Button size="sm" onClick={resetFilters}>{t('Сбросить фильтры')}</Button>} />
          ) : (
            kind === 'renewal' ? (
              <EmptyState icon={Inbox} title={t('Продлений пока нет')} description={t('Продления появятся здесь, когда их создадут с экрана «Продления» или автоматически — когда абонемент заканчивается.')} />
            ) : (
              <EmptyState icon={Inbox} title={t('Заявок пока нет')} description={t('Заявки из Instagram, WhatsApp и звонков появятся здесь — по колонкам воронки.')} action={<Button variant="primary" icon={Plus} onClick={openQuickLead}>{t('Новая заявка')}</Button>} />
            )
          )}
        </div>
      ) : (
        <>
          <MobileColumn board={board} stage={mobileColumn} onStageChange={setMobileStage} onMove={requestMove} onLoadMore={loadMore} returnTo={returnTo} />
          <Board board={board} onMove={requestMove} onLoadMore={loadMore} returnTo={returnTo} />
          <p className="mt-3 text-xs text-ink-subtle">
            {t('«Купил абонемент» и «Отказ» — за последние {n} дней. Задайте период в фильтрах, чтобы увидеть старые.', { n: board.closed_days })}
          </p>
        </>
      )}

      {rejecting && (
        <RejectModal
          lead={rejecting.lead}
          onCancel={() => setRejecting(null)}
          onConfirm={async extra => { const { lead, stage } = rejecting; setRejecting(null); await move(lead, stage, extra) }}
        />
      )}
    </div>
  )
}

/** Доска или таблица — два вида одной воронки с общими фильтрами. */
function ViewToggle({ view, onChange }) {
  const options = [
    { value: 'board', label: t('Доска'), icon: Columns3 },
    { value: 'table', label: t('Таблица'), icon: Table2 },
  ]
  return (
    <div className="flex rounded-[10px] bg-surface-muted p-1" role="tablist" aria-label={t('Вид')}>
      {options.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="tab"
          aria-selected={view === value}
          onClick={() => onChange(value)}
          className={cn(
            'flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-semibold transition-colors',
            view === value ? 'bg-surface text-brand-600 shadow-sm' : 'text-ink-muted hover:text-ink',
          )}
        >
          <Icon className="size-4" />
          {label}
        </button>
      ))}
    </div>
  )
}

function moveCard(board, lead, target) {
  return {
    ...board,
    columns: board.columns.map(column => {
      if (column.stage === lead.stage) return { ...column, count: column.count - 1, results: column.results.filter(r => r.id !== lead.id) }
      if (column.stage === target.stage) {
        const moved = { ...lead, stage: target.stage, stage_name: target.label, stage_color: target.color, status: target.status, days_in_status: 0, is_stale: false }
        return { ...column, count: column.count + 1, results: [moved, ...column.results] }
      }
      return column
    }),
  }
}

function replaceCard(board, lead) {
  return { ...board, columns: board.columns.map(column => ({ ...column, results: column.results.map(r => (r.id === lead.id ? lead : r)) })) }
}

/** Десктоп: все колонки; перетаскивание подсвечивает только допустимые. */
function Board({ board, onMove, onLoadMore, returnTo }) {
  const [dragging, setDragging] = useState(null)
  const [over, setOver] = useState(null)
  const allowed = dragging ? board.stage_transitions[dragging.stage] || [] : []

  return (
    <div className="hidden overflow-x-auto pb-2 md:block">
      <div className="flex min-w-max gap-3">
        {board.columns.map(column => {
          const canDrop = dragging && allowed.includes(column.stage)
          return (
            <section
              key={column.stage}
              aria-label={column.label}
              onDragOver={e => { if (canDrop) { e.preventDefault(); setOver(column.stage) } }}
              onDragLeave={() => setOver(o => (o === column.stage ? null : o))}
              onDrop={e => {
                e.preventDefault()
                setOver(null)
                if (canDrop) onMove(dragging, column.stage)
                setDragging(null)
              }}
              className={cn(
                'flex w-[264px] shrink-0 flex-col rounded-xl border bg-surface-muted/60 transition-colors',
                over === column.stage ? 'border-brand-400 bg-brand-50' : canDrop ? 'border-dashed border-brand-300' : 'border-line',
                dragging && !canDrop && column.stage !== dragging.stage && 'opacity-50',
              )}
            >
              <ColumnHeader column={column} />
              <div className="flex min-h-24 flex-col gap-2 p-2">
                {column.results.map(lead => (
                  <LeadCard
                    key={lead.id}
                    lead={lead}
                    draggable
                    dragging={dragging?.id === lead.id}
                    onDragStart={() => setDragging(lead)}
                    onDragEnd={() => { setDragging(null); setOver(null) }}
                    onMove={onMove}
                    board={board}
                    returnTo={returnTo}
                  />
                ))}
                {column.has_more && <Button size="sm" variant="ghost" onClick={() => onLoadMore(column.stage)}>{t('Показать ещё')}</Button>}
              </div>
            </section>
          )
        })}
      </div>
      {dragging && (
        <OutcomeBar
          columns={board.columns}
          allowed={allowed}
          over={over}
          setOver={setOver}
          onDrop={stage => { setOver(null); onMove(dragging, stage); setDragging(null) }}
        />
      )}
    </div>
  )
}

const OUTCOMES = ['purchased', 'thinking', 'rejected']

/**
 * Итоги воронки — всегда под рукой, пока тянут карточку: на обычном
 * экране все семь колонок не помещаются, и «Отказ» оказался бы за краем.
 */
function OutcomeBar({ columns, allowed, over, setOver, onDrop }) {
  // Основные этапы исходов — у центра они могут называться по-своему.
  const outcomes = OUTCOMES.map(status => columns.find(c => c.is_system && c.status === status)).filter(Boolean)
  return (
    <div className="fixed inset-x-0 bottom-4 z-40 flex justify-center px-4">
      <div className="flex gap-2 rounded-2xl border border-line bg-surface/95 p-2 shadow-pop backdrop-blur">
        {outcomes.map(column => {
          const { status } = column
          const enabled = allowed.includes(column.stage)
          const key = `outcome:${column.stage}`
          return (
            <div
              key={column.stage}
              onDragOver={e => { if (enabled) { e.preventDefault(); setOver(key) } }}
              onDragLeave={() => setOver(o => (o === key ? null : o))}
              onDrop={e => { e.preventDefault(); if (enabled) onDrop(column.stage) }}
              className={cn(
                'flex w-44 items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-4 text-sm font-semibold transition-colors',
                !enabled && 'border-line text-ink-subtle opacity-40',
                enabled && over !== key && 'border-line-strong text-ink',
                enabled && over === key && (status === 'rejected' ? 'border-danger-600 bg-danger-50 text-danger-600' : status === 'purchased' ? 'border-success-600 bg-success-50 text-success-600' : 'border-brand-400 bg-brand-50 text-brand-600'),
              )}
            >
              <span className={cn('size-2 rounded-full', STAGE_DOT[column.color])} />
              {column.label}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** Телефон: одна колонка и переключатель этапа — без горизонтального скролла. */
function MobileColumn({ board, stage, onStageChange, onMove, onLoadMore, returnTo }) {
  const column = board.columns.find(c => c.stage === stage)
  const options = board.columns.map(c => ({ value: c.stage, label: `${c.label} · ${c.count}` }))
  if (!column) return null
  return (
    <div className="md:hidden">
      <Dropdown value={stage} onChange={onStageChange} options={options} ariaLabel={t('Колонка воронки')} className="mb-3" />
      <div className="flex flex-col gap-2">
        {column.results.length === 0 && <p className="rounded-xl border border-dashed border-line bg-surface px-4 py-6 text-center text-sm text-ink-muted">{t('В этой колонке пусто')}</p>}
        {column.results.map(lead => <LeadCard key={lead.id} lead={lead} onMove={onMove} board={board} returnTo={returnTo} />)}
        {column.has_more && <Button size="sm" onClick={() => onLoadMore(column.stage)}>{t('Показать ещё')}</Button>}
      </div>
    </div>
  )
}

function ColumnHeader({ column }) {
  return (
    <header className="flex items-center gap-2 px-3 pb-1 pt-3">
      <span className={cn('size-2 shrink-0 rounded-full', STAGE_DOT[column.color])} />
      <h2 className="truncate text-[13px] font-bold text-ink">{column.label}</h2>
      <span className="ml-auto rounded-full bg-surface px-2 py-0.5 text-[11px] font-semibold text-ink-muted">{column.count}</span>
    </header>
  )
}

function LeadCard({ lead, draggable = false, dragging = false, onDragStart, onDragEnd, onMove, board, returnTo }) {
  const navigate = useNavigate()
  const targets = board.stage_transitions[lead.stage] || []
  const details = [lead.child_age != null && ageLabel(lead.child_age), lead.direction_name].filter(Boolean).join(' · ')
  return (
    <article
      draggable={draggable}
      onDragStart={e => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', lead.id); onDragStart?.() }}
      onDragEnd={onDragEnd}
      onClick={() => navigate(`/leads/${lead.id}`, { state: { leadsReturnTo: returnTo } })}
      onKeyDown={e => { if (e.key === 'Enter') navigate(`/leads/${lead.id}`, { state: { leadsReturnTo: returnTo } }) }}
      tabIndex={0}
      className={cn(
        'cursor-pointer rounded-lg border bg-surface p-3 shadow-xs transition hover:border-brand-300 focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-brand-50',

        draggable && 'cursor-grab active:cursor-grabbing',
        lead.is_stale ? 'border-warning-600/40' : 'border-line',
        dragging && 'opacity-40',
      )}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">{leadTitle(lead)}</p>
          {lead.child_name && <p className="truncate text-xs text-ink-muted">{lead.parent_name}</p>}
        </div>
        {targets.length > 0 && <MoveMenu lead={lead} columns={board.columns} targets={targets} onMove={onMove} />}
      </div>
      {details && <p className="mt-1.5 truncate text-xs text-ink-muted">{details}</p>}
      {lead.status === 'trial_attended' && !lead.converted_child && (
        <p className="mt-2 rounded-md bg-brand-50 px-2 py-1 text-xs font-semibold text-brand-700">{t('Оформить клиента')}</p>
      )}
      <div className="mt-2.5 flex items-center gap-2 text-[11px]">
        {lead.source_name && <span className="truncate rounded-full bg-surface-muted px-2 py-0.5 font-semibold text-ink-muted">{t(lead.source_name)}</span>}
        <span className={cn('ml-auto flex shrink-0 items-center gap-1', lead.is_stale ? 'font-semibold text-warning-600' : 'text-ink-subtle')} title={lead.is_stale ? t('Висит без движения') : t('Дней в статусе')}>
          {lead.is_stale && <AlarmClock className="size-3.5" />}
          {lead.days_in_status === 0 ? t('сегодня') : t('{n} дн.', { n: lead.days_in_status })}
        </span>
        {lead.assigned_to_name && <Avatar name={lead.assigned_to_name} className="!size-5 !text-[9px]" />}
      </div>
    </article>
  )
}

/** Сменить этап без перетаскивания: телефон, клавиатура. */
function MoveMenu({ lead, columns, targets, onMove }) {
  const options = columns.filter(c => targets.includes(c.stage)).map(c => ({ value: c.stage, label: c.label }))
  return (
    <span className="shrink-0" onClick={e => e.stopPropagation()} onKeyDown={e => e.stopPropagation()}>
      <Dropdown
        size="sm"
        value=""
        onChange={to => onMove(lead, to)}
        options={options}
        placeholder={<ArrowRightLeft className="size-3.5" />}
        ariaLabel={t('Сменить статус: {name}', { name: leadTitle(lead) })}
        className="!h-7 !w-auto !gap-0 !px-1.5 [&>svg:last-child]:hidden"
      />
    </span>
  )
}

function LeadFilters({ params, update, lists, branches, onReset }) {
  const applied = Object.fromEntries(FILTER_KEYS.map(key => [key, params.get(key) || '']))
  const { draft, set, dirty } = useFilterDraft(applied)
  return (
    <FilterPanel dirty={dirty} canReset={FILTER_KEYS.some(key => applied[key])} onApply={() => update(draft)} onReset={onReset}>
      <FilterSelect label={t('Источник')} value={draft.source} onChange={v => set('source', v)} options={[['', t('Все источники')], ...lists.sources.map(s => [String(s.id), t(s.name)])]} />
      <FilterSelect label={t('Направление')} value={draft.direction} onChange={v => set('direction', v)} options={[['', t('Все направления')], ...lists.directions.map(d => [String(d.id), d.name])]} />
      {branches.length > 1 && (
        <FilterSelect label={t('Филиал')} value={draft.branch} onChange={v => set('branch', v)} options={[['', t('Как в шапке')], ...branches.map(b => [String(b.id), b.name])]} />
      )}
      <FilterSelect label={t('Ответственный')} value={draft.assigned_to} onChange={v => set('assigned_to', v)} options={[['', t('Все')], ['me', t('Мои')], ...lists.staff.map(u => [String(u.id), u.full_name])]} />
      <div className="w-full xl:w-40">
        <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Создана с')}</p>
        <DateInput value={draft.created_from} onChange={v => set('created_from', v)} />
      </div>
      <div className="w-full xl:w-40">
        <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('по')}</p>
        <DateInput value={draft.created_to} onChange={v => set('created_to', v)} />
      </div>
    </FilterPanel>
  )
}

function BoardSkeleton() {
  return (
    <div className="flex gap-3 overflow-hidden">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="w-full space-y-2 rounded-xl border border-line bg-surface-muted/60 p-3 md:w-[264px]">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ))}
    </div>
  )
}
