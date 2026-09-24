import { useRef, useState } from 'react'
import { FileSpreadsheet, Upload } from 'lucide-react'
import api from '../api/axios'
import { Badge, Button, Modal, Select, apiErrorMessage, cn } from '../ui'

// Импорт — тот же жизненный цикл, что у веб-экрана импорта (backend:
// domains/people/clients/import_jobs.py): файл → сухой прогон в фоне (без
// записи в базу) → отчёт и решения по найденным дублям → импорт одной
// транзакцией → итог. Значения строк здесь не правятся: ошибки исправляются
// в самом файле и он загружается заново (ТЗ п. 4.1, TRU-36).
// Отдельная страница импорта с историей и откатом — TRU-84.
const IMPORT_API = 'clients/children/import'
const LEVELS = {
  ready: { tone: 'success', label: 'Готово' },
  warning: { tone: 'warning', label: 'Предупреждение' },
  error: { tone: 'danger', label: 'Ошибка' },
}
const RESULT_ROWS = [
  ['children_created', 'Создано детей'],
  ['parents_created', 'Создано родителей'],
  ['attached_to_existing_parent', 'Привязано к существующим родителям'],
  ['linked_to_existing_child', 'Привязано к существующим детям'],
  ['enrolled_in_groups', 'Записано в группы'],
  ['skipped', 'Пропущено'],
]

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms))

export default function ImportModal({ onClose, onImported }) {
  const [file, setFile] = useState(null)
  const [dryRun, setDryRun] = useState(null)
  const [decisions, setDecisions] = useState({})
  const [waiting, setWaiting] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const fileRef = useRef(null)

  // Сухой прогон и импорт идут в фоне — опрашиваем статус задачи.
  async function waitForJob(jobId, label) {
    for (;;) {
      const { data: job } = await api.get(`${IMPORT_API}/jobs/${jobId}/`)
      if (job.status === 'done') return job
      if (job.status === 'failed') throw new Error(job.error_message || 'Ошибка задачи импорта')
      setWaiting(job.progress ? `${label}: ${job.progress.done} из ${job.progress.total}` : `${label}…`)
      await sleep(1500)
    }
  }

  async function upload() {
    setError('')
    setWaiting('Загрузка файла…')
    try {
      const body = new FormData()
      body.append('file', file)
      const { data } = await api.post(`${IMPORT_API}/preview/`, body)
      const job = await waitForJob(data.job_id, 'Проверка файла')
      setDecisions(Object.fromEntries(
        job.rows.filter(r => r.duplicate).map(r => [r.row_number, r.duplicate.options[0]]),
      ))
      setDryRun(job)
    } catch (err) {
      setError(err.response ? apiErrorMessage(err) : err.message)
    } finally {
      setWaiting('')
    }
  }

  async function confirm() {
    setError('')
    setWaiting('Запуск импорта…')
    try {
      const { data } = await api.post(`${IMPORT_API}/confirm/`, { job_id: dryRun.job_id, decisions })
      setResult(await waitForJob(data.job_id, 'Запись в базу'))
    } catch (err) {
      setError(err.response ? apiErrorMessage(err) : err.message)
    } finally {
      setWaiting('')
    }
  }

  const importable = dryRun ? dryRun.ready_count + dryRun.warning_count : 0
  let title = 'Импорт из Excel'
  let footer = (
    <>
      <Button onClick={onClose}>Отмена</Button>
      <Button variant="primary" onClick={upload} disabled={!file} loading={Boolean(waiting)}>Проверить файл</Button>
    </>
  )
  if (result) {
    title = 'Импорт завершён'
    footer = <Button variant="primary" onClick={onImported}>Готово</Button>
  } else if (dryRun) {
    title = 'Проверка файла'
    footer = (
      <>
        <Button onClick={() => setDryRun(null)} disabled={Boolean(waiting)}>Другой файл</Button>
        <Button variant="primary" onClick={confirm} disabled={!importable} loading={Boolean(waiting)}>
          Импортировать ({importable})
        </Button>
      </>
    )
  }

  return (
    <Modal open onClose={waiting ? undefined : onClose} title={title} size={dryRun && !result ? 'xl' : 'md'} footer={footer}>
      {waiting && <p className="mb-3 text-sm text-ink-muted" role="status">{waiting}</p>}
      {error && <p className="mb-3 rounded-md bg-danger-50 px-3 py-2 text-sm text-danger-600">{error}</p>}

      {result && (
        <dl className="divide-y divide-line rounded-lg border border-line">
          {RESULT_ROWS.map(([key, label]) => (
            <div key={key} className="flex items-center justify-between px-4 py-2.5 text-sm">
              <dt className="text-ink-muted">{label}</dt>
              <dd className="font-bold text-ink">{result[key] ?? 0}</dd>
            </div>
          ))}
        </dl>
      )}

      {!result && dryRun && (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            <Badge tone="success">Готово: {dryRun.ready_count}</Badge>
            <Badge tone="warning">С предупреждениями: {dryRun.warning_count}</Badge>
            <Badge tone="danger">С ошибками (пропустим): {dryRun.error_count}</Badge>
          </div>
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[720px] text-[13px]">
              <thead className="bg-surface-muted text-left text-xs uppercase tracking-wide text-ink-subtle">
                <tr>
                  {['Строка', 'Статус', 'Ребёнок', 'Сообщения', 'Совпадение', 'Решение'].map(h => (
                    <th key={h} className="px-3 py-2 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dryRun.rows.map(row => {
                  const level = LEVELS[row.level]
                  const dup = row.duplicate
                  return (
                    <tr key={row.row_number} className="border-t border-line align-top">
                      <td className="px-3 py-2 text-ink-subtle">{row.row_number}</td>
                      <td className="px-3 py-2"><Badge tone={level.tone}>{level.label}</Badge></td>
                      <td className="px-3 py-2 font-medium text-ink">{row.child_name || '—'}</td>
                      <td className="px-3 py-2 text-ink-muted">{row.messages.join('; ') || '—'}</td>
                      <td className="px-3 py-2 text-ink-muted">{dup ? `${dup.kind_label}: ${dup.matched}` : '—'}</td>
                      <td className="min-w-52 px-3 py-2">
                        {dup && (
                          <Select
                            aria-label={`Решение для строки ${row.row_number}`}
                            className="h-9"
                            value={decisions[row.row_number]}
                            onChange={e => setDecisions(d => ({ ...d, [row.row_number]: e.target.value }))}
                          >
                            {dup.options.map(option => <option key={option} value={option}>{dup.option_labels[option]}</option>)}
                          </Select>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!result && !dryRun && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className={cn(
              'flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors',
              file ? 'border-brand-400 bg-brand-50' : 'border-line hover:border-line-strong hover:bg-surface-muted',
            )}
          >
            {file ? <FileSpreadsheet className="size-7 text-brand-600" /> : <Upload className="size-7 text-ink-subtle" />}
            <span className={cn('text-sm', file ? 'font-semibold text-brand-700' : 'text-ink-muted')}>
              {file ? file.name : 'Выберите файл .xlsx или .csv'}
            </span>
          </button>
          <input ref={fileRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={e => setFile(e.target.files[0] || null)} />
          <div className="rounded-lg bg-surface-muted px-4 py-3 text-[13px] leading-relaxed text-ink-muted">
            <p className="font-semibold text-ink">Какие колонки нужны</p>
            <ul className="mt-1 list-disc pl-5">
              <li>ФИО ребёнка, дата рождения, пол — обязательно</li>
              <li>ФИО и телефон родителя — обязательно</li>
              <li>Роль родителя, мед. заметки, направление, группа — по желанию</li>
            </ul>
            <p className="mt-2">Сначала файл проверяется без записи в базу — вы увидите ошибки и возможные дубли.</p>
          </div>
        </div>
      )}
    </Modal>
  )
}
