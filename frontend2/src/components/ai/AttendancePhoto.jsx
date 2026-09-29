import { useRef, useState } from 'react'
import { Camera, Check, HelpCircle, X } from 'lucide-react'
import api from '../../api/axios'
import { markAttendance } from '../../api/attendance'
import { Button, Modal, apiErrorMessage, cn, useToast } from '../../ui'
import { t } from '../../i18n'
import { AIBadge } from './ai'

const STATUSES = [
  { value: 'present', icon: Check, get label() { return t('Был') }, tone: 'border-success-600 bg-success-50 text-success-600' },
  { value: 'absent', icon: X, get label() { return t('Не был') }, tone: 'border-danger-600 bg-danger-50 text-danger-600' },
  { value: 'unknown', icon: HelpCircle, get label() { return t('Пропустить') }, tone: 'border-line-strong bg-surface-muted text-ink-muted' },
]

/**
 * Посещаемость по фото бумажного журнала (эксперимент ИИ): снимок → ИИ
 * предлагает «был/не был» по списку занятия → преподаватель правит → сохраняем
 * обычными отметками (как кнопками на экране). «Пропустить» — не трогаем.
 */
export default function AttendancePhoto({ lessonId, onClose, onSaved }) {
  const toast = useToast()
  const inputRef = useRef(null)
  const [preview, setPreview] = useState(null)
  const [marks, setMarks] = useState(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  async function upload(file) {
    if (!file) return
    setPreview(URL.createObjectURL(file))
    setBusy(true)
    const body = new FormData()
    body.append('lesson', lessonId)
    body.append('image', file)
    try {
      const res = await api.post('ai/attendance-photo/', body)
      setMarks(res.data.marks)
      setNote(res.data.note)
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    const toSave = marks.filter(m => m.status !== 'unknown')
    setBusy(true)
    const results = await Promise.allSettled(toSave.map(m => markAttendance({ lesson: lessonId, child: m.child, status: m.status })))
    setBusy(false)
    const failed = results.filter(r => r.status === 'rejected').length
    if (failed) toast.error(t('Не сохранилось: {n}', { n: failed }))
    else toast.success(t('Отмечено: {n}', { n: toSave.length }))
    onSaved()
  }

  const counts = marks ? Object.fromEntries(STATUSES.map(s => [s.value, marks.filter(m => m.status === s.value).length])) : {}

  return (
    <Modal
      open
      onClose={onClose}
      title={<span className="flex items-center gap-2">{t('Отметить по фото журнала')} <AIBadge /></span>}
      description={t('Сфотографируйте журнал или доску — ИИ предложит отметки, вы проверите и сохраните.')}
      footer={marks ? (
        <>
          <Button onClick={() => inputRef.current?.click()} icon={Camera}>{t('Другое фото')}</Button>
          <Button variant="primary" loading={busy} disabled={!counts.present && !counts.absent} onClick={save}>
            {t('Сохранить отметки')}
          </Button>
        </>
      ) : null}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }}
      />
      {!marks && (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed border-[#c4b5fd] bg-[#faf5ff] px-4 py-8 text-[#7c3aed] hover:bg-[#f3e8ff]"
        >
          {preview && <img src={preview} alt="" className="mb-2 max-h-40 rounded-md object-contain" />}
          <Camera className="size-7" />
          <span className="text-sm font-semibold">{busy ? t('ИИ читает журнал…') : t('Сделать или выбрать фото')}</span>
        </button>
      )}
      {marks && (
        <div className="space-y-3">
          <p className="text-[13px] text-ink-muted">
            {t('Был: {p} · Не был: {a} · Не разобрано: {u}', { p: counts.present, a: counts.absent, u: counts.unknown })}
          </p>
          {note && <p className="rounded-md bg-warning-50 px-3 py-2 text-[13px] text-warning-600">{note}</p>}
          <ul className="max-h-[50vh] divide-y divide-line overflow-y-auto rounded-lg border border-line">
            {marks.map(mark => (
              <li key={mark.child} className="flex items-center gap-2 px-3 py-2">
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{mark.full_name}</span>
                {STATUSES.map(s => {
                  const Icon = s.icon
                  const active = mark.status === s.value
                  return (
                    <button
                      key={s.value}
                      type="button"
                      title={s.label}
                      aria-label={`${mark.full_name}: ${s.label}`}
                      aria-pressed={active}
                      onClick={() => setMarks(ms => ms.map(m => (m.child === mark.child ? { ...m, status: s.value } : m)))}
                      className={cn('flex size-8 items-center justify-center rounded-md border', active ? s.tone : 'border-line text-ink-subtle hover:bg-surface-muted')}
                    >
                      <Icon className="size-4" />
                    </button>
                  )
                })}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  )
}
