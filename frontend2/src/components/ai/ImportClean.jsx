import { useRef, useState } from 'react'
import { AlertTriangle, Download, Sparkles, Wand2 } from 'lucide-react'
import api from '../../api/axios'
import { Button, Modal, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'
import { AIBadge, useAI } from './ai'

const XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

function toFile(base64, name) {
  const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0))
  return new File([bytes], name, { type: XLSX })
}

/**
 * «Грязная» таблица → наш шаблон (эксперимент ИИ). ИИ только раскладывает
 * данные по колонкам; дальше исправленный файл идёт обычным импортом —
 * сопоставление, сухой прогон, решения по дублям.
 */
export default function ImportClean({ onUse }) {
  const ai = useAI()
  const toast = useToast()
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  if (!ai.enabled) return null

  async function clean(file) {
    if (!file) return
    setBusy(true)
    const body = new FormData()
    body.append('file', file)
    try {
      const res = await api.post('ai/import-clean/', body)
      setResult({ ...res.data, name: file.name.replace(/\.(xlsx|csv)$/i, '') + ' — исправлено ИИ.xlsx' })
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function download() {
    const url = URL.createObjectURL(toFile(result.file, result.name))
    Object.assign(document.createElement('a'), { href: url, download: result.name }).click()
    URL.revokeObjectURL(url)
  }

  const shown = result?.rows.slice(0, 50) || []

  return (
    <>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="mt-4 flex w-full items-center gap-3 rounded-lg border border-dashed border-[#c4b5fd] bg-[#faf5ff] px-4 py-3 text-left hover:bg-[#f3e8ff]"
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#ede9fe] text-[#7c3aed]">
          <Wand2 className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-[#7c3aed]">
            {busy ? t('ИИ приводит таблицу к шаблону… до минуты') : t('Таблица «грязная»? ИИ приведёт её к шаблону')}
          </span>
          <span className="block text-xs text-ink-muted">{t('Несколько телефонов в ячейке, «мама 8707…», имя вместе с датой — разложит по колонкам')}</span>
        </span>
      </button>
      <input ref={inputRef} type="file" accept=".xlsx,.csv" className="hidden" onChange={e => { clean(e.target.files?.[0]); e.target.value = '' }} />

      {result && (
        <Modal
          open
          size="xl"
          onClose={() => setResult(null)}
          title={<span className="flex items-center gap-2">{t('Таблица после ИИ')} <AIBadge /></span>}
          description={t('Строк в файле: {src} → детей: {rows}. Проверить: {p}. Дальше — обычный импорт с проверкой и дублями.', { src: result.source_rows, rows: result.rows.length, p: result.problems })}
          footer={
            <>
              <Button icon={Download} onClick={download}>{t('Скачать')}</Button>
              <Button variant="primary" icon={Sparkles} onClick={() => { const file = toFile(result.file, result.name); setResult(null); onUse(file) }}>
                {t('Продолжить импорт')}
              </Button>
            </>
          }
        >
          <div className="max-h-[55vh] overflow-auto rounded-lg border border-line">
            <table className="w-full text-[13px]">
              <thead className="sticky top-0 bg-surface-muted text-left text-[11px] uppercase text-ink-subtle">
                <tr>
                  {['Ребёнок', 'Дата рожд.', 'Пол', 'Родитель', 'Телефон', 'Роль', 'Проверить'].map(h => <th key={h} className="px-3 py-2 font-semibold">{t(h)}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {shown.map((row, i) => (
                  <tr key={i} className={row.problem ? 'bg-warning-50/50' : ''}>
                    <td className="px-3 py-1.5 font-medium text-ink">{row.child_name}</td>
                    <td className="px-3 py-1.5">{row.birth_date || <span className="text-danger-600">—</span>}</td>
                    <td className="px-3 py-1.5">{row.gender || <span className="text-danger-600">—</span>}</td>
                    <td className="px-3 py-1.5">{row.parent_name}</td>
                    <td className="whitespace-nowrap px-3 py-1.5">{row.phone}</td>
                    <td className="px-3 py-1.5">{row.role}</td>
                    <td className="px-3 py-1.5 text-warning-600">
                      {row.problem && <span className="inline-flex items-center gap-1"><AlertTriangle className="size-3.5 shrink-0" />{row.problem}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.rows.length > shown.length && (
            <p className="mt-2 text-xs text-ink-subtle">{t('Показаны первые {n} — весь файл можно скачать.', { n: shown.length })}</p>
          )}
        </Modal>
      )}
    </>
  )
}
