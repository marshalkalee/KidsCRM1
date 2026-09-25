import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, Check, X, RotateCcw, AlertTriangle, Loader2, Users, MapPin, Clock, ChevronRight, WifiOff,
} from 'lucide-react'
import { localDatePart, localTimePart } from '../utils/calendarDate'
import { fetchTodayLessons } from '../api/lessons'
import { fetchLesson, fetchAttendanceRoster, markAttendance, markAllPresent } from '../api/attendance'

const ACCENT = '#C97B6E'
const MOBILE_BREAKPOINT = 640 // TRU-51: отдельный сценарий для телефона, не адаптив десктопа

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

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < MOBILE_BREAKPOINT)
  useEffect(() => {
    function handler() { setIsMobile(window.innerWidth < MOBILE_BREAKPOINT) }
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])
  return isMobile
}

// ТЗ п. 10.4/13.3: плохая связь не должна незаметно терять отметку —
// баннер сверху виден всё время, пока связи нет (независимо от того, шло
// ли в этот момент сохранение), плюс у каждой строки есть свой признак
// "не сохранилось" (см. AttendanceRow) на случай обрыва посреди запроса.
function useOnlineStatus() {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    function goOnline() { setOnline(true) }
    function goOffline() { setOnline(false) }
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])
  return online
}

// Вход в посещаемость: без ?lesson — список занятий на сегодня (свои для
// преподавателя, все для админа/владельца — фильтрует бэк), с ?lesson —
// сам экран отметки. Из сайдбара — занятие открывается за два нажатия:
// «Посещаемость» → карточка занятия в списке; если занятие на сегодня
// ровно одно (типичный случай — преподаватель зашёл перед своим уроком),
// список сразу же ведёт дальше сам, без выбора — это и даёт буквально два
// нажатия «от входа в систему» (критерий приёмки TRU-51).
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
      .then(data => {
        if (data.length === 1) {
          navigate(`/attendance?lesson=${data[0].id}`, { replace: true })
          return
        }
        setLessons(data)
      })
      .catch(() => setError('Не удалось загрузить занятия на сегодня.'))
      .finally(() => setLoading(false))
  }, [navigate])

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

// Экран отметки: десктоп (TRU-56) — компактные кнопки в ряд, причина
// пропуска раскрывается внутри строки. Телефон (TRU-51) — отдельный
// сценарий, не адаптив: кнопки на весь ряд под палец, причина — шторка
// снизу экрана, «отметить всех» прибита к низу (работа одной рукой).
// Всё остальное (мгновенная реакция, автосохранение, признак «не
// сохранилось», ≤3 клика на ребёнка) общее для обеих версий.
function AttendanceLessonScreen({ lessonId }) {
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const online = useOnlineStatus()

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
  const reasonPickerRow = rows.find(r => r.child === reasonPickerFor)

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

  const bulkButton = (
    <button
      style={{ ...primaryBtn, width: '100%', opacity: bulkSaving ? 0.6 : 1 }}
      disabled={bulkSaving || markedCount === rows.length}
      onClick={handleMarkAllPresent}
    >
      {bulkSaving ? <Loader2 size={15} /> : <Check size={15} />}
      Отметить всех пришедшими
    </button>
  )

  return (
    // Запас снизу под прибитую кнопку на телефоне — иначе последняя
    // строка списка оказалась бы под ней (перекрытие, не горизонтальный
    // скролл, но та же суть — не должно мешать взаимодействию).
    <div style={{ fontFamily: 'Manrope', maxWidth: 640, margin: '0 auto', paddingBottom: isMobile ? 84 : 0 }}>
      {!online && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', marginBottom: 14,
          borderRadius: 10, background: '#FEF3C7', color: '#92400E', fontSize: 12.5, fontWeight: 600,
        }}>
          <WifiOff size={15} /> Нет связи — отметки не сохранятся, пока она не появится
        </div>
      )}

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

      {!isMobile && <div style={{ marginBottom: 16 }}>{bulkButton}</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map(row => (
          <AttendanceRow
            key={row.child}
            row={row}
            mobile={isMobile}
            saving={!!savingIds[row.child]}
            onOpenReasonPicker={() => setReasonPickerFor(row.child)}
            onMark={(statusValue, reason) => handleMark(row.child, statusValue, reason)}
          />
        ))}
      </div>

      {isMobile && (
        <div style={{
          position: 'fixed', left: 0, right: 0, bottom: 0, padding: '10px 16px',
          background: '#fff', borderTop: '1px solid #F0F0F5', boxShadow: '0 -4px 16px rgba(0,0,0,0.06)',
        }}>
          {bulkButton}
        </div>
      )}

      {isMobile && reasonPickerRow && (
        <AbsenceReasonSheet
          childName={reasonPickerRow.child_name}
          onSelect={reason => handleMark(reasonPickerRow.child, 'absent', reason)}
          onClose={() => setReasonPickerFor(null)}
        />
      )}
    </div>
  )
}

function AttendanceRow({ row, mobile, saving, onOpenReasonPicker, onMark }) {
  const isPresent = row.status === 'present'
  const isAbsent = row.status === 'absent'
  const isMakeup = row.status === 'makeup'
  const [reasonPickerOpenDesktop, setReasonPickerOpenDesktop] = useState(false)

  function handleAbsentClick() {
    // Телефон — шторка снизу экрана (AbsenceReasonSheet, управляется
    // родителем через reasonPickerFor); десктоп — раскрытие тут же в
    // строке, ближе к месту клика, без лишнего визуального шума модалки.
    if (mobile) onOpenReasonPicker()
    else setReasonPickerOpenDesktop(true)
  }

  const statusButtons = (
    <div style={{ display: 'flex', gap: mobile ? 8 : 6, flexShrink: 0, width: mobile ? '100%' : 'auto' }}>
      <StatusButton mobile={mobile} active={isPresent} color="#16A34A" icon={Check} label="Пришёл" saving={saving} onClick={() => onMark('present')} />
      <StatusButton mobile={mobile} active={isAbsent} color="#DC2626" icon={X} label="Не был" saving={saving} onClick={handleAbsentClick} />
      <StatusButton mobile={mobile} active={isMakeup} color={ACCENT} icon={RotateCcw} label="Отработка" saving={saving} onClick={() => onMark('makeup')} />
    </div>
  )

  const statusNote = (
    <>
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
    </>
  )

  if (mobile) {
    // Вертикально: имя — крупные кнопки на всю ширину под ней (под палец,
    // не под мышь), никакого горизонтального сжатия при длинном имени.
    return (
      <div style={{ background: '#fff', border: '1px solid #F0F0F5', borderRadius: 14, padding: 14 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: '#1A1A2E' }}>{row.child_name}</div>
        {statusNote}
        <div style={{ marginTop: 10 }}>{statusButtons}</div>
      </div>
    )
  }

  return (
    <div style={{ background: '#fff', border: '1px solid #F0F0F5', borderRadius: 14, padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#1A1A2E', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {row.child_name}
          </div>
          {statusNote}
        </div>
        {statusButtons}
      </div>

      {reasonPickerOpenDesktop && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #F0F0F5', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {ABSENCE_REASONS.map(([value, label]) => (
            <button key={value} style={reasonChip} onClick={() => { setReasonPickerOpenDesktop(false); onMark('absent', value) }}>
              {label}
            </button>
          ))}
          <button style={{ ...reasonChip, color: '#9CA3AF' }} onClick={() => setReasonPickerOpenDesktop(false)}>Отмена</button>
        </div>
      )}
    </div>
  )
}

// Шторка снизу (TRU-51) вместо модалки в центре — большой палец достаёт
// без переноса руки, закрывается тапом по подложке.
function AbsenceReasonSheet({ childName, onSelect, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'flex-end' }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', background: '#fff', borderRadius: '20px 20px 0 0', padding: '20px 16px 28px',
          fontFamily: 'Manrope',
        }}
      >
        <div style={{ width: 36, height: 4, borderRadius: 2, background: '#E5E7EB', margin: '0 auto 16px' }} />
        <div style={{ fontSize: 13, color: '#9CA3AF', marginBottom: 2 }}>Причина пропуска</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#1A1A2E', marginBottom: 16 }}>{childName}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {ABSENCE_REASONS.map(([value, label]) => (
            <button key={value} style={sheetOption} onClick={() => onSelect(value)}>{label}</button>
          ))}
          <button style={{ ...sheetOption, color: '#9CA3AF', border: 'none', background: 'transparent' }} onClick={onClose}>
            Отмена
          </button>
        </div>
      </div>
    </div>
  )
}

function StatusButton({ mobile, active, color, icon: Icon, label, saving, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={saving}
      title={label}
      style={mobile ? {
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4,
        flex: 1, padding: '12px 4px', borderRadius: 12, cursor: saving ? 'default' : 'pointer',
        border: active ? `1.5px solid ${color}` : '1.5px solid #EBEBF0',
        background: active ? `${color}14` : '#fff',
        color: active ? color : '#6B7280',
        opacity: saving ? 0.6 : 1,
        fontFamily: 'Manrope', fontSize: 12, fontWeight: 700,
      } : {
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
        width: 58, padding: '8px 4px', borderRadius: 10, cursor: saving ? 'default' : 'pointer',
        border: active ? `1.5px solid ${color}` : '1.5px solid #EBEBF0',
        background: active ? `${color}14` : '#fff',
        color: active ? color : '#9CA3AF',
        opacity: saving ? 0.6 : 1,
        fontFamily: 'Manrope', fontSize: 10, fontWeight: 700,
      }}
    >
      <Icon size={mobile ? 20 : 16} />
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

const sheetOption = {
  padding: '14px 16px', borderRadius: 12, border: '1px solid #EBEBF0', background: '#fff',
  fontSize: 15, fontWeight: 600, color: '#1A1A2E', cursor: 'pointer', fontFamily: 'Manrope',
  textAlign: 'left', width: '100%',
}
