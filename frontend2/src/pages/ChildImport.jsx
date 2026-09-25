import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowRight, CheckCircle2, Download, History, RotateCcw, Upload, XCircle,
} from 'lucide-react'
import api from '../api/axios'
import {
  Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, Select, Spinner, apiErrorMessage, cn,
  formatDateTime, plural, useConfirm, useToast,
} from '../ui'
import { t } from '../i18n'

// Импорт детей из Excel (TRU-84) — тот же жизненный цикл, что у старого
// веба (backend: import_api_views.py): файл → маппинг колонок → сухой
// прогон в фоне (без записи в базу) → отчёт и решения по дублям → импорт
// одной транзакцией → итог и откат. Текущая задача — в адресе (?job=),
// поэтому обновление страницы не теряет прогресс.
const IMPORT_API = 'clients/children/import'
const STEPS = [t('Файл'), t('Колонки'), t('Проверка'), t('Импорт')]
const LEVELS = {
  ready: { tone: 'success', label: t('Готово') },
  warning: { tone: 'warning', label: t('Предупреждение') },
  error: { tone: 'danger', label: t('Ошибка') },
}
const REPORT_PAGE = 50

export default function ChildImport() {
  const [params, setParams] = useSearchParams()
  const jobId = params.get('job')
  const [draft, setDraft] = useState(null) // { file, analysis } — до запуска сухого прогона
  const [loadedJob, setLoadedJob] = useState(null)

  const openJob = useCallback(id => {
    setDraft(null)
    setParams(id ? { job: id } : {})
  }, [setParams])

  let step = 0
  let body
  if (jobId) {
    body = <JobView key={jobId} jobId={jobId} openJob={openJob} onLoaded={setLoadedJob} />
    const job = loadedJob?.job_id === jobId ? loadedJob : null
    step = job?.job_type === 'execute' ? (job.status === 'done' ? STEPS.length : 3) : 2
  } else if (draft) {
    body = <MappingStep draft={draft} onBack={() => setDraft(null)} onStarted={openJob} />
    step = 1
  } else {
    body = <FileStep onAnalyzed={setDraft} openJob={openJob} />
  }

  return (
    <div>
      <PageHeader
        back={{ to: '/children', label: t('Дети') }}
        title={t('Импорт из Excel')}
        description={t('Сначала файл проверяется без записи в базу — вы увидите ошибки и возможные дубли.')}
      />
      <JobStepper step={step} />
      {body}
    </div>
  )
}

function JobStepper({ step }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-2 text-[13px]" aria-label={t('Шаги импорта')}>
      {STEPS.map((label, index) => {
        const done = index < step
        const current = index === step
        return (
          <li key={label} className="flex items-center gap-2">
            <span className={cn(
              'flex size-6 items-center justify-center rounded-full text-xs font-bold',
              done ? 'bg-success-50 text-success-600' : current ? 'bg-brand-600 text-white' : 'bg-surface-muted text-ink-subtle',
            )}>
              {done ? <CheckCircle2 className="size-4" /> : index + 1}
            </span>
            <span className={cn('font-semibold', current ? 'text-ink' : 'text-ink-muted')}>{label}</span>
            {index < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-line-strong" />}
          </li>
        )
      })}
    </ol>
  )
}

// --- Шаг 1: файл -----------------------------------------------------------

function FileStep({ onAnalyzed, openJob }) {
  const [file, setFile] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const fileRef = useRef(null)

  async function analyze(chosen) {
    setFile(chosen)
    setError('')
    setLoading(true)
    try {
      const body = new FormData()
      body.append('file', chosen)
      const { data } = await api.post(`${IMPORT_API}/analyze/`, body)
      onAnalyzed({ file: chosen, analysis: data })
    } catch (err) {
      setError(err.response?.data?.file?.[0] || apiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          onDragOver={e => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={e => {
            e.preventDefault()
            setDragging(false)
            if (e.dataTransfer.files[0]) analyze(e.dataTransfer.files[0])
          }}
          disabled={loading}
          className={cn(
            'flex w-full flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors',
            dragging ? 'border-brand-400 bg-brand-50' : 'border-line hover:border-line-strong hover:bg-surface-muted',
          )}
        >
          <span className="flex size-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
            {loading ? <Spinner className="py-0" label="" /> : <Upload className="size-6" />}
          </span>
          <span className="text-base font-semibold text-ink">{file ? file.name : t('Перетащите файл сюда или выберите')}</span>
          <span className="text-sm text-ink-muted">{t('.xlsx или .csv, первая строка — заголовки')}</span>
        </button>
        <input ref={fileRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={e => e.target.files[0] && analyze(e.target.files[0])} />
        {error && <p className="mt-3 rounded-md bg-danger-50 px-3 py-2 text-sm text-danger-600">{error}</p>}
        <div className="mt-5 rounded-lg bg-surface-muted px-4 py-3 text-[13px] leading-relaxed text-ink-muted">
          <p className="font-semibold text-ink">{t('Что должно быть в файле')}</p>
          <ul className="mt-1 list-disc pl-5">
            <li>{t('ФИО ребёнка, дата рождения, пол — обязательно')}</li>
            <li>{t('ФИО и телефон родителя — обязательно')}</li>
            <li>{t('Роль родителя, мед. заметки, остаток занятий, направление, группа — по желанию')}</li>
          </ul>
          <p className="mt-2">{t('Названия колонок могут быть любыми — на следующем шаге вы сопоставите их с полями.')}</p>
        </div>
      </Card>
      <ImportHistory openJob={openJob} />
    </div>
  )
}

function ImportHistory({ openJob }) {
  const [jobs, setJobs] = useState(null)
  useEffect(() => {
    api.get(`${IMPORT_API}/jobs/`).then(r => setJobs(r.data.results)).catch(() => setJobs([]))
  }, [])
  return (
    <Card>
      <CardHeader title={t('Прошлые импорты')} description={t('Откатить можно, пока с данными не начали работать')} />
      {!jobs && <Spinner className="py-4" />}
      {jobs && jobs.length === 0 && <p className="text-sm text-ink-muted">{t('Импортов ещё не было.')}</p>}
      {jobs && jobs.length > 0 && (
        <ul className="-mx-2 space-y-1">
          {jobs.map(job => (
            <li key={job.job_id}>
              <button type="button" onClick={() => openJob(job.job_id)} className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-surface-muted">
                <History className="size-4 shrink-0 text-ink-subtle" />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink">
                    {job.children_created} {plural(job.children_created, ['ребёнок', 'ребёнка', 'детей'])}
                  </span>
                  <span className="block truncate text-xs text-ink-subtle">{formatDateTime(job.created_at)} · {job.created_by}</span>
                </span>
                {job.rolled_back_at ? <Badge>{t('Откатан')}</Badge> : job.status === 'failed' ? <Badge tone="danger">{t('Ошибка')}</Badge> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

// --- Шаг 2: маппинг колонок --------------------------------------------------

function MappingStep({ draft, onBack, onStarted }) {
  const { file, analysis } = draft
  const [mapping, setMapping] = useState(analysis.mapping)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  const missing = analysis.fields.filter(f => f.required && !mapping[f.key])
  // Одна колонка — одно поле: выбрали её здесь — снимаем с другого поля,
  // иначе «Кто привёл» молча ушла бы и в ФИО родителя, и в роль.
  const choose = (key, header) => setMapping(m => {
    const next = Object.fromEntries(Object.entries(m).map(([k, v]) => [k, header && v === header ? null : v]))
    return { ...next, [key]: header }
  })
  const sample = key => {
    const index = analysis.headers.indexOf(mapping[key])
    if (index < 0) return null
    return analysis.preview_rows.map(row => row.values[index]).find(v => v !== '' && v != null) ?? null
  }

  async function start() {
    setSaving(true)
    setError('')
    try {
      const body = new FormData()
      body.append('file', file)
      body.append('mapping', JSON.stringify(mapping))
      const { data } = await api.post(`${IMPORT_API}/preview/`, body)
      onStarted(data.job_id)
    } catch (err) {
      const data = err.response?.data
      setError(data?.mapping?.[0] || data?.file?.[0] || apiErrorMessage(err))
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t('Какая колонка что означает')}
          description={analysis.mapping_saved
            ? t('Для файла с такими колонками маппинг уже сохранён — проверьте и продолжайте.')
            : t('Мы угадали, что смогли. Поправьте, если что-то не так — выбор запомнится для таких файлов.')}
          actions={<Badge>{file.name} · {analysis.total_rows} {plural(analysis.total_rows, ['строка', 'строки', 'строк'])}</Badge>}
        />
        <div className="divide-y divide-line rounded-lg border border-line">
          {analysis.fields.map(field => {
            const value = sample(field.key)
            const invalid = field.required && !mapping[field.key]
            return (
              <div key={field.key} className="grid items-center gap-2 px-4 py-3 sm:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)] sm:gap-4">
                <span className="text-sm font-semibold text-ink">
                  {t(field.label)}
                  {field.required && <span className="ml-0.5 text-danger-600">*</span>}
                </span>
                <Select
                  aria-label={t(field.label)}
                  invalid={invalid}
                  className="h-9"
                  value={mapping[field.key] || ''}
                  onChange={e => choose(field.key, e.target.value || null)}
                >
                  <option value="">{t('— не импортировать —')}</option>
                  {analysis.headers.map(header => <option key={header} value={header}>{header}</option>)}
                </Select>
                <span className="truncate text-[13px] text-ink-muted">
                  {value != null ? <>{t('например:')} <span className="text-ink">{String(value)}</span></> : <span className="text-ink-subtle">—</span>}
                </span>
              </div>
            )
          })}
        </div>
      </Card>

      <Card padded={false}>
        <CardHeader className="mb-0 px-5 pt-5" title={t('Первые строки файла')} />
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] text-[13px]">
            <thead className="bg-surface-muted text-left text-xs text-ink-subtle">
              <tr>
                <th className="px-3 py-2 font-semibold">№</th>
                {analysis.headers.map(h => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {analysis.preview_rows.map(row => (
                <tr key={row.row_number} className="border-t border-line">
                  <td className="px-3 py-2 text-ink-subtle">{row.row_number}</td>
                  {row.values.map((v, i) => <td key={i} className="px-3 py-2 text-ink">{v === '' || v == null ? '—' : String(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Button onClick={onBack}>{t('Другой файл')}</Button>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          {missing.length > 0 && <p className="text-sm text-danger-600">{t('Выберите колонки:')} {missing.map(f => t(f.label)).join(', ')}</p>}
          {error && <p className="text-sm text-danger-600">{error}</p>}
          <Button variant="primary" icon={ArrowRight} loading={saving} disabled={missing.length > 0} onClick={start}>{t('Проверить файл')}</Button>
        </div>
      </div>
    </div>
  )
}

// --- Шаги 3–4: задача (сухой прогон или импорт) -----------------------------

function JobView({ jobId, openJob, onLoaded }) {
  const [job, setJobState] = useState(null)
  const [error, setError] = useState(false)
  const setJob = useCallback(data => { setJobState(data); onLoaded(data) }, [onLoaded])

  const load = useCallback(() => api.get(`${IMPORT_API}/jobs/${jobId}/`).then(r => { setJob(r.data); setError(false); return r.data }), [jobId, setJob])

  // Фоновая задача — опрашиваем, пока не закончится.
  useEffect(() => {
    let timer
    let cancelled = false
    const tick = () => load()
      .then(data => {
        if (!cancelled && (data.status === 'pending' || data.status === 'running')) timer = setTimeout(tick, 1200)
      })
      .catch(() => { if (!cancelled) setError(true) })
    tick()
    return () => { cancelled = true; clearTimeout(timer) }
  }, [load])

  if (error) return <Card><ErrorState title={t('Задача импорта не найдена')} onRetry={() => openJob(null)} /></Card>
  if (!job) return <Spinner />
  if (job.status === 'pending' || job.status === 'running') {
    return <ProgressCard job={job} />
  }
  if (job.status === 'failed') {
    return (
      <Card>
        <EmptyState icon={XCircle} title={t('Не получилось')} description={job.error_message || t('Задача завершилась с ошибкой. Ничего не записано.')} action={<Button onClick={() => openJob(null)}>{t('Начать заново')}</Button>} />
      </Card>
    )
  }
  return job.job_type === 'dry_run'
    ? <DryRunReport job={job} setJob={setJob} openJob={openJob} />
    : <ImportResult job={job} reload={load} openJob={openJob} />
}

function ProgressCard({ job }) {
  const { done = 0, total = job.total_rows || 0 } = job.progress || {}
  const percent = total ? Math.round((done / total) * 100) : 0
  return (
    <Card className="mx-auto max-w-xl text-center">
      <p className="text-base font-semibold text-ink">{job.job_type === 'dry_run' ? t('Проверяем файл…') : t('Записываем в базу…')}</p>
      <p className="mt-1 text-sm text-ink-muted">{t('Можно не ждать на этой странице — прогресс сохранится.')}</p>
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-surface-muted" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${Math.max(percent, 4)}%` }} />
      </div>
      <p className="mt-2 text-[13px] text-ink-muted">{done} {t('из')} {total}</p>
    </Card>
  )
}

const FILTERS = [
  ['all', t('Все')],
  ['error', t('Ошибки')],
  ['warning', t('Предупреждения')],
  ['duplicate', t('Совпадения')],
  ['ready', t('Готовы')],
]

function DryRunReport({ job, setJob, openJob }) {
  const toast = useToast()
  const [filter, setFilter] = useState(() => (job.error_count ? 'error' : job.rows.some(r => r.duplicate) ? 'duplicate' : 'all'))
  const [shown, setShown] = useState(REPORT_PAGE)
  const [decisions, setDecisions] = useState(() => job.decisions || {})
  const [bulk, setBulk] = useState({})
  const [starting, setStarting] = useState(false)

  const importable = job.ready_count + job.warning_count
  const duplicates = job.rows.filter(r => r.duplicate).length
  const rows = useMemo(() => job.rows.filter(row => {
    if (filter === 'all') return true
    if (filter === 'duplicate') return Boolean(row.duplicate)
    return row.level === filter
  }), [job.rows, filter])

  async function applyBulk(kind) {
    const decision = bulk[kind.kind] || kind.options[0].value
    try {
      const { data } = await api.post(`${IMPORT_API}/jobs/${job.job_id}/decisions/`, { bulk_kind: kind.kind, bulk_decision: decision })
      setJob(data)
      setDecisions(data.decisions)
      toast.success(t('Решение применено: {count}', { count: `${kind.count} ${plural(kind.count, ['строка', 'строки', 'строк'])}` }))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function download() {
    try {
      const { data } = await api.get(`${IMPORT_API}/jobs/${job.job_id}/report.xlsx`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const link = Object.assign(document.createElement('a'), { href: url, download: `import_report_${job.job_id}.xlsx` })
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function start() {
    setStarting(true)
    try {
      const { data } = await api.post(`${IMPORT_API}/confirm/`, { job_id: job.job_id, decisions })
      openJob(data.job_id)
    } catch (err) {
      toast.error(apiErrorMessage(err))
      setStarting(false)
    }
  }

  if (job.executed_job_id) {
    return (
      <Card>
        <EmptyState icon={CheckCircle2} title={t('Из этой проверки уже запущен импорт')} action={<Button variant="primary" onClick={() => openJob(job.executed_job_id)}>{t('Открыть импорт')}</Button>} />
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat tone="success" icon={CheckCircle2} label={t('Готовы к импорту')} value={job.ready_count} />
        <Stat tone="warning" icon={AlertTriangle} label={t('С предупреждениями')} value={job.warning_count} hint={t('будут импортированы')} />
        <Stat tone="danger" icon={XCircle} label={t('С ошибками')} value={job.error_count} hint={t('пропустим — исправьте в файле')} />
      </div>

      {job.duplicate_kinds?.length > 0 && (
        <Card>
          <CardHeader title={t('Найдены совпадения')} description={t('Решите сразу для всех строк одного вида — или по отдельности в таблице ниже.')} />
          <div className="grid gap-3 md:grid-cols-2">
            {job.duplicate_kinds.map(kind => (
              <div key={kind.kind} className="rounded-lg border border-line p-4">
                <p className="text-sm font-semibold text-ink">{t(kind.label)} <span className="font-normal text-ink-muted">· {kind.count}</span></p>
                <div className="mt-2 flex gap-2">
                  <Select aria-label={t('Решение: {kind}', { kind: t(kind.label) })} className="h-9" value={bulk[kind.kind] || kind.options[0].value} onChange={e => setBulk(b => ({ ...b, [kind.kind]: e.target.value }))}>
                    {kind.options.map(option => <option key={option.value} value={option.value}>{t(option.label)}</option>)}
                  </Select>
                  <Button size="sm" className="h-9" onClick={() => applyBulk(kind)}>{t('Для всех')}</Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card padded={false}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-5">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('Фильтр строк')}>
            {FILTERS.map(([value, label]) => {
              const count = value === 'all' ? job.rows.length : value === 'duplicate' ? duplicates : job[`${value}_count`]
              return (
                <button
                  key={value}
                  type="button"
                  aria-pressed={filter === value}
                  onClick={() => { setFilter(value); setShown(REPORT_PAGE) }}
                  className={cn(
                    'rounded-full border px-3 py-1 text-[13px] font-medium',
                    filter === value ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line text-ink-muted hover:text-ink',
                  )}
                >
                  {label} <span className="text-ink-subtle">{count}</span>
                </button>
              )
            })}
          </div>
          <Button size="sm" icon={Download} onClick={download}>{t('Скачать отчёт')}</Button>
        </div>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[760px] text-[13px]">
            <thead className="bg-surface-muted text-left text-xs uppercase tracking-wide text-ink-subtle">
              <tr>
                {[t('Строка'), t('Статус'), t('Ребёнок'), t('Что не так'), t('Совпадение'), t('Решение')].map(h => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, shown).map(row => {
                const level = LEVELS[row.level]
                const dup = row.duplicate
                return (
                  <tr key={row.row_number} className="border-t border-line align-top">
                    <td className="px-3 py-2 text-ink-subtle">{row.row_number}</td>
                    <td className="px-3 py-2"><Badge tone={level.tone}>{level.label}</Badge></td>
                    <td className="px-3 py-2 font-medium text-ink">{row.child_name || '—'}</td>
                    <td className="px-3 py-2 text-ink-muted">{row.messages.join('; ') || '—'}</td>
                    <td className="px-3 py-2 text-ink-muted">{dup ? <><span className="text-ink">{t(dup.kind_label)}</span><br />{dup.matched}</> : '—'}</td>
                    <td className="min-w-56 px-3 py-2">
                      {dup && (
                        <Select
                          aria-label={t('Решение для строки {n}', { n: row.row_number })}
                          className="h-9"
                          value={decisions[row.row_number] || dup.options[0]}
                          onChange={e => setDecisions(d => ({ ...d, [row.row_number]: e.target.value }))}
                        >
                          {dup.options.map(option => <option key={option} value={option}>{t(dup.option_labels[option])}</option>)}
                        </Select>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {rows.length === 0 && <p className="px-5 py-6 text-center text-sm text-ink-muted">{t('Таких строк нет.')}</p>}
        </div>
        {rows.length > shown && (
          <div className="border-t border-line px-5 py-3 text-center">
            <Button variant="ghost" size="sm" onClick={() => setShown(s => s + REPORT_PAGE)}>{t('Показать ещё (')}{rows.length - shown})</Button>
          </div>
        )}
      </Card>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-between">
        <Button onClick={() => openJob(null)}>{t('Загрузить другой файл')}</Button>
        <Button variant="primary" icon={ArrowRight} loading={starting} disabled={!importable} onClick={start}>
          {t('Импортировать {count}', { count: `${importable} ${plural(importable, ['строку', 'строки', 'строк'])}` })}
        </Button>
      </div>
    </div>
  )
}

function Stat({ tone, icon: Icon, label, value, hint }) {
  const tones = {
    success: 'bg-success-50 text-success-600',
    warning: 'bg-warning-50 text-warning-600',
    danger: 'bg-danger-50 text-danger-600',
  }
  return (
    <Card className="flex items-center gap-4">
      <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-full', tones[tone])}><Icon className="size-5" /></span>
      <div>
        <p className="text-2xl font-bold text-ink">{value}</p>
        <p className="text-[13px] text-ink-muted">{label}{hint && <span className="text-ink-subtle"> — {hint}</span>}</p>
      </div>
    </Card>
  )
}

const RESULT_ROWS = [
  ['children_created', t('Создано детей')],
  ['parents_created', t('Создано родителей')],
  ['attached_to_existing_parent', t('Привязано к существующим родителям')],
  ['linked_to_existing_child', t('Дописано к существующим детям')],
  ['enrolled_in_groups', t('Записано в группы')],
  ['skipped', t('Пропущено по решению')],
]

function ImportResult({ job, reload, openJob }) {
  const navigate = useNavigate()
  const toast = useToast()
  const confirm = useConfirm()
  const [rolling, setRolling] = useState(false)

  async function rollback() {
    const ok = await confirm({
      title: t('Откатить импорт?'),
      message: t('Все дети, родители и связи, созданные этим импортом, будут удалены.'),
      confirmText: t('Откатить'),
      danger: true,
    })
    if (!ok) return
    setRolling(true)
    try {
      await api.post(`${IMPORT_API}/jobs/${job.job_id}/rollback/`)
      toast.success(t('Импорт откатан'))
      await reload()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setRolling(false)
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px] lg:items-start">
      <Card>
        <div className="mb-4 flex items-center gap-3">
          <span className={cn('flex size-11 items-center justify-center rounded-full', job.rolled_back_at ? 'bg-surface-muted text-ink-muted' : 'bg-success-50 text-success-600')}>
            {job.rolled_back_at ? <RotateCcw className="size-5" /> : <CheckCircle2 className="size-5" />}
          </span>
          <div>
            <p className="text-base font-bold text-ink">{job.rolled_back_at ? t('Импорт откатан') : t('Импорт завершён')}</p>
            {job.rolled_back_at && <p className="text-[13px] text-ink-muted">{formatDateTime(job.rolled_back_at)}</p>}
          </div>
        </div>
        <dl className="divide-y divide-line rounded-lg border border-line">
          {RESULT_ROWS.map(([key, label]) => (
            <div key={key} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <dt className="text-ink-muted">{label}</dt>
              <dd className="font-bold text-ink">{job[key] ?? 0}</dd>
            </div>
          ))}
        </dl>
        {job.not_imported?.length > 0 && (
          <div className="mt-4 rounded-lg bg-warning-50 p-4 text-sm">
            <p className="font-semibold text-warning-600">{t('Не импортированы:')} {job.not_imported.length}</p>
            <ul className="mt-1 list-disc pl-5 text-ink">
              {job.not_imported.slice(0, 20).map(([row, reason]) => <li key={row}>{t('строка')} {row}: {reason}</li>)}
            </ul>
          </div>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => navigate('/children')}>{t('К списку детей')}</Button>
          <Button onClick={() => openJob(null)}>{t('Ещё один файл')}</Button>
        </div>
      </Card>

      {!job.rolled_back_at && (
        <Card>
          <CardHeader title={t('Откат')} description={t('Удаляет всё, что создал этот импорт — если что-то пошло не так.')} />
          {job.rollback_blockers?.length ? (
            <div className="rounded-lg bg-surface-muted p-3 text-[13px] text-ink-muted">
              <p className="font-semibold text-ink">{t('Откатить уже нельзя:')}</p>
              <ul className="mt-1 list-disc pl-5">
                {job.rollback_blockers.map(reason => <li key={reason}>{reason}</li>)}
              </ul>
            </div>
          ) : (
            <Button variant="danger-ghost" icon={RotateCcw} loading={rolling} onClick={rollback}>{t('Откатить импорт')}</Button>
          )}
        </Card>
      )}
    </div>
  )
}
