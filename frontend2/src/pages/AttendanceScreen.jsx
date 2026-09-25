import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, Check, X, RotateCcw, AlertTriangle, Loader2, Users, MapPin, Clock, ChevronRight,
} from 'lucide-react'
import { localDatePart, localTimePart } from '../utils/calendarDate'
import { fetchTodayLessons } from '../api/lessons'
import { fetchLesson, fetchAttendanceRoster, markAttendance, markAllPresent } from '../api/attendance'

const ACCENT = '#C97B6E'

const ABSENCE_REASONS = [
  ['illness', 'Болезнь'],
  ['family', 'Семейные обстоятельства'],
  ['no_reason', 'Без причины'],
]

const CONSUME_OUTCOME_LABEL = {
  no_active_subscription: 'Нет абонемента',
  subscription_frozen: 'Абонемент заморожен',
  subscription_exhausted: 'Занятия закончились',
  rule_forbids: 'Абонемент не позволяет списание',
}

function lessonLabel(lesson) {
  if (!lesson) return ''
  if (lesson.group_name) return lesson.group_name
  if (lesson.individual_children_names?.length) return lesson.individual_children_names.join(', ')
  return 'Индив. занятие'
}

// Вход в посещаемость: без ?lesson — список занятий на сегодня (свои для
// преподавателя, все для админа/владельца — фильтрует бэк), с ?lesson —
// сам экран отметки. Из сайдбара — занятие открывается за два нажатия:
// «Посещаемость» → карточка занятия в списке (критерий приёмки TRU-51,
// уже выполняется и для десктопа).
export default function AttendanceScreen() {
  const [searchParams] = useSearchParams()
  const lessonId = searchParams.get('lesson')
  return lessonId ? <AttendanceLessonScreen lessonId={lessonId} /> : <TodayLessonsList />
}

function TodayLessonsList() {
  const navigate = useNavigate()
  const [lessons, setLessons] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    fetchTodayLessons()
      .then(setLessons)
      .catch(() => setError('Не удалось загрузить занятия на сегодня.'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={{ fontFamily: 'Manrope', maxWidth: 640, margin: '0 auto' }}>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: '0 0 4px' }}>Посещаемость</h1>
      <p style={{ fontSize: 13, color: '#9CA3AF', margin: '0 0 18px' }}>Занятия на сегодня</p>

      {loading && <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF' }}>Загрузка…</div>}
      {error && <div style={{ padding: 24, textAlign: 'center', color: '#DC2626' }}>{error}</div>}
      {!loading && !error && lessons.length === 0 && (
        <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF' }}>Сегодня занятий нет.</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {lessons.map(lesson => (
          <button
            key={lesson.id}
            onClick={() => navigate(`/attendance?lesson=${lesson.id}`)}
            style={{
              display: 'flex', alignItems: 'center', gap: 10, width: '100%', textAlign: 'left',
              background: '#fff', border: '1px solid #F0F0F5', borderRadius: 14, padding: '12px 14px',
              cursor: 'pointer', fontFamily: 'Manrope',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#1A1A2E' }}>{lessonLabel(lesson)}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 12, color: '#6B7280', marginTop: 3 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Clock size={12} /> {localTimePart(lesson.starts_at_local)}–{localTimePart(lesson.ends_at_local)}
                </span>
                {lesson.room_name && (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <MapPin size={12} /> {lesson.room_name}
                  </span>
                )}
              </div>
            </div>
            <ChevronRight size={16} style={{ color: '#C7C7D1', flexShrink: 0 }} />
          </button>
        ))}
      </div>
    </div>
  )
}

// Сам экран отметки (TRU-56): преподаватель/администратор отмечает статус
// ребёнка ОДНИМ нажатием (≤3 клика на ребёнка — ТЗ п. 10.4), причина
// пропуска — сразу под кнопкой «не был», без перехода на другой экран.
// Сохранение — на каждое нажатие сразу (нет кнопки «Сохранить»); при
// ошибке строка ребёнка помечается явно, чтобы отметка не потерялась
// незаметно.
function AttendanceLessonScreen({ lessonId }) {
  const navigate = useNavigate()

  const [lesson, setLesson] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reasonPickerFor, setReasonPickerFor] = useState(null)
  const [savingIds, setSavingIds] = useState({})
  const [bulkSaving, setBulkSaving] = useState(false)

  const load = useCallback(() => {
    if (!lessonId) {
      setError('Не указано занятие.')
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    Promise.all([fetchLesson(lessonId), fetchAttendanceRoster(lessonId)])
      .then(([lessonData, rosterData]) => {
        setLesson(lessonData)
        setRows(rosterData.results)
      })
      .catch(err => {
        setError(
          err.response?.status === 403
            ? 'Доступно только для своих занятий.'
            : 'Не удалось загрузить занятие.'
        )
      })
      .finally(() => setLoading(false))
  }, [lessonId])

  useEffect(() => { load() }, [load])

  async function handleMark(childId, statusValue, absenceReason = '') {
    setReasonPickerFor(null)
    setSavingIds(s => ({ ...s, [childId]: true }))
    // Мгновенная реакция на нажатие — обновляем строку сразу, не дожидаясь
    // ответа сервера; при ошибке откатываем и показываем, что не сохранилось.
    setRows(rs => rs.map(r => (
      r.child === childId
        ? { ...r, status: statusValue, absence_reason: absenceReason, _error: false }
        : r
    )))
    try {
      const updated = await markAttendance({ lesson: lessonId, child: childId, status: statusValue, absenceReason })
      setRows(rs => rs.map(r => (r.child === childId ? { ...r, ...updated, _error: false } : r)))
    } catch {
      setRows(rs => rs.map(r => (r.child === childId ? { ...r, _error: true } : r)))
    } finally {
      setSavingIds(s => ({ ...s, [childId]: false }))
    }
  }

  async function handleMarkAllPresent() {
    setBulkSaving(true)
    try {
      await markAllPresent(lessonId)
      load()
    } catch {
      setError('Не удалось отметить всех — попробуйте ещё раз.')
      setBulkSaving(false)
    }
  }

  const markedCount = rows.filter(r => r.status).length

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#9CA3AF', fontFamily: 'Manrope' }}>
        Загрузка…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: 'Manrope' }}>
        <p style={{ color: '#DC2626', marginBottom: 16 }}>{error}</p>
        <button style={backBtn} onClick={() => navigate('/attendance')}>
          <ArrowLeft size={14} /> К списку занятий
        </button>
      </div>
    )
  }

  return (
    <div style={{ fontFamily: 'Manrope', maxWidth: 640, margin: '0 auto' }}>
      <button style={{ ...backBtn, marginBottom: 12 }} onClick={() => navigate('/attendance')}>
        <ArrowLeft size={14} /> К списку занятий
      </button>

      <div style={{ background: '#fff', border: '1px solid #F0F0F5', borderRadius: 16, padding: 18, marginBottom: 16 }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', marginBottom: 6 }}>
          {lessonLabel(lesson)}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, fontSize: 12.5, color: '#6B7280' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Clock size={13} /> {localDatePart(lesson.starts_at_local)} · {localTimePart(lesson.starts_at_local)}–{localTimePart(lesson.ends_at_local)}
          </span>
          {lesson.room_name && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <MapPin size={13} /> {lesson.room_name}
            </span>
          )}
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Users size={13} /> {markedCount}/{rows.length} отмечено
          </span>
        </div>
      </div>

      <button
        style={{ ...primaryBtn, width: '100%', marginBottom: 16, opacity: bulkSaving ? 0.6 : 1 }}
        disabled={bulkSaving || markedCount === rows.length}
        onClick={handleMarkAllPresent}
      >
        {bulkSaving ? <Loader2 size={15} /> : <Check size={15} />}
        Отметить всех пришедшими
      </button>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map(row => (
          <AttendanceRow
            key={row.child}
            row={row}
            saving={!!savingIds[row.child]}
            reasonPickerOpen={reasonPickerFor === row.child}
            onOpenReasonPicker={() => setReasonPickerFor(row.child)}
            onCloseReasonPicker={() => setReasonPickerFor(null)}
            onMark={(statusValue, reason) => handleMark(row.child, statusValue, reason)}
          />
        ))}
      </div>
    </div>
  )
}

function AttendanceRow({ row, saving, reasonPickerOpen, onOpenReasonPicker, onCloseReasonPicker, onMark }) {
  const isPresent = row.status === 'present'
  const isAbsent = row.status === 'absent'
  const isMakeup = row.status === 'makeup'

  return (
    <div style={{ background: '#fff', border: '1px solid #F0F0F5', borderRadius: 14, padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1A1A2E', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {row.child_name}
          </div>
          {row._error && (
            <div style={{ fontSize: 11, color: '#DC2626', marginTop: 2 }}>
              Не сохранилось — нажмите ещё раз
            </div>
          )}
          {!row._error && row.status === 'present' && row.consumed_from_subscription && (
            <div style={{ fontSize: 11, color: '#16A34A', marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
              <Check size={11} /> Списано с абонемента
            </div>
          )}
          {!row._error && row.status === 'present' && !row.consumed_from_subscription && row.no_subscription_flag && (
            <div style={{ fontSize: 11.5, fontWeight: 700, color: '#D97706', marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
              <AlertTriangle size={12} /> Нет абонемента
            </div>
          )}
          {!row._error && row.status === 'present' && !row.consumed_from_subscription && !row.no_subscription_flag && CONSUME_OUTCOME_LABEL[row.consume_outcome] && (
            <div style={{ fontSize: 11.5, color: '#D97706', marginTop: 2 }}>
              {CONSUME_OUTCOME_LABEL[row.consume_outcome]}
            </div>
          )}
          {isAbsent && row.absence_reason && (
            <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>
              {ABSENCE_REASONS.find(([v]) => v === row.absence_reason)?.[1]}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <StatusButton active={isPresent} color="#16A34A" icon={Check} label="Пришёл" saving={saving} onClick={() => onMark('present')} />
          <StatusButton active={isAbsent} color="#DC2626" icon={X} label="Не был" saving={saving} onClick={onOpenReasonPicker} />
          <StatusButton active={isMakeup} color={ACCENT} icon={RotateCcw} label="Отработка" saving={saving} onClick={() => onMark('makeup')} />
        </div>
      </div>

      {reasonPickerOpen && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #F0F0F5', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {ABSENCE_REASONS.map(([value, label]) => (
            <button key={value} style={reasonChip} onClick={() => onMark('absent', value)}>
              {label}
            </button>
          ))}
          <button style={{ ...reasonChip, color: '#9CA3AF' }} onClick={onCloseReasonPicker}>Отмена</button>
        </div>
      )}
    </div>
  )
}

function StatusButton({ active, color, icon: Icon, label, saving, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={saving}
      title={label}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
        width: 58, padding: '8px 4px', borderRadius: 10, cursor: saving ? 'default' : 'pointer',
        border: active ? `1.5px solid ${color}` : '1.5px solid #EBEBF0',
        background: active ? `${color}14` : '#fff',
        color: active ? color : '#9CA3AF',
        opacity: saving ? 0.6 : 1,
        fontFamily: 'Manrope', fontSize: 10, fontWeight: 700,
      }}
    >
      <Icon size={16} />
      {label}
    </button>
  )
}

const primaryBtn = {
  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
  padding: '11px 18px', border: 'none', borderRadius: 10,
  background: `linear-gradient(135deg, #E8998D, ${ACCENT})`, color: '#fff',
  fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: 'Manrope',
}

const backBtn = {
  display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px',
  border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff',
  fontSize: 12.5, fontWeight: 600, color: '#6B7280', cursor: 'pointer', fontFamily: 'Manrope',
}

const reasonChip = {
  padding: '7px 12px', borderRadius: 20, border: '1px solid #EBEBF0', background: '#fff',
  fontSize: 12, fontWeight: 600, color: '#1A1A2E', cursor: 'pointer', fontFamily: 'Manrope',
}
