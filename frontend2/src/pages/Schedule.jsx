import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, X, Users, MapPin, User as UserIcon, Plus } from 'lucide-react'
import {
  startOfWeek, addDays, toISODate, isToday, formatWeekRange, formatDayLabel,
  localDatePart, localTimePart, timeToMinutes, WEEKDAY_LABELS,
} from '../utils/calendarDate'
import { fetchLessons, fetchGroups, fetchRooms, fetchTeachers, createLesson, cancelLesson, rescheduleLesson } from '../api/lessons'

const ACCENT = '#C97B6E'
const DEFAULT_COLOR = '#7C6FF7'
const ROW_HEIGHT = 56 // px за час
const MOBILE_BREAKPOINT = 860

const STATUS_LABEL = {
  scheduled: 'Запланировано',
  completed: 'Проведено',
  cancelled: 'Отменено',
  rescheduled: 'Перенесено',
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

// Раскладка занятий одного дня по колонкам, чтобы пересекающиеся по времени
// не наезжали друг на друга (простой greedy-алгоритм интервального графа).
function layoutDay(lessons) {
  const sorted = [...lessons].sort((a, b) => a.startMin - b.startMin)
  const columns = [] // конец последнего занятия в колонке
  const placed = sorted.map(lesson => {
    let col = columns.findIndex(end => end <= lesson.startMin)
    if (col === -1) { col = columns.length; columns.push(lesson.endMin) }
    else columns[col] = lesson.endMin
    return { ...lesson, col }
  })
  const totalCols = columns.length || 1
  return placed.map(l => ({ ...l, totalCols }))
}

export default function Schedule() {
  const [weekStart, setWeekStart] = useState(() => startOfWeek(new Date()))
  const [lessons, setLessons] = useState([])
  const [loading, setLoading] = useState(true)
  const [groups, setGroups] = useState([])
  const [rooms, setRooms] = useState([])
  const [teachers, setTeachers] = useState([])
  const [selectedLesson, setSelectedLesson] = useState(null)
  const [createSlot, setCreateSlot] = useState(null)
  const [mobileDay, setMobileDay] = useState(0)
  const isMobile = useIsMobile()
  const navigate = useNavigate()

  const weekDays = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])

  const load = useCallback(() => {
    setLoading(true)
    const from = toISODate(weekStart)
    const to = toISODate(addDays(weekStart, 6))
    fetchLessons(from, to)
      .then(setLessons)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [weekStart])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    Promise.all([fetchGroups(), fetchRooms(), fetchTeachers()])
      .then(([g, r, t]) => { setGroups(g); setRooms(r); setTeachers(t) })
      .catch(console.error)
  }, [])

  const byDay = useMemo(() => {
    const map = {}
    weekDays.forEach(d => { map[toISODate(d)] = [] })
    lessons.forEach(lesson => {
      const dateStr = localDatePart(lesson.starts_at_local)
      const timeStr = localTimePart(lesson.starts_at_local)
      const endStr = localTimePart(lesson.ends_at_local)
      if (!map[dateStr]) return
      map[dateStr].push({
        ...lesson,
        startMin: timeToMinutes(timeStr),
        endMin: timeToMinutes(endStr),
      })
    })
    Object.keys(map).forEach(k => { map[k] = layoutDay(map[k]) })
    return map
  }, [lessons, weekDays])

  const { gridStartHour, gridEndHour } = useMemo(() => {
    let min = 8, max = 21
    lessons.forEach(l => {
      const startH = Math.floor(timeToMinutes(localTimePart(l.starts_at_local)) / 60)
      const endH = Math.ceil(timeToMinutes(localTimePart(l.ends_at_local)) / 60)
      if (startH < min) min = startH
      if (endH > max) max = endH
    })
    return { gridStartHour: min, gridEndHour: max }
  }, [lessons])

  const hours = useMemo(
    () => Array.from({ length: gridEndHour - gridStartHour }, (_, i) => gridStartHour + i),
    [gridStartHour, gridEndHour]
  )

  function goToday() { setWeekStart(startOfWeek(new Date())); setMobileDay(new Date().getDay() === 0 ? 6 : new Date().getDay() - 1) }
  function goPrevWeek() { setWeekStart(w => addDays(w, -7)) }
  function goNextWeek() { setWeekStart(w => addDays(w, 7)) }

  function handleActionDone() { setSelectedLesson(null); setCreateSlot(null); load() }

  return (
    <div>
      <CalendarHeader
        weekStart={weekStart}
        onPrev={goPrevWeek}
        onNext={goNextWeek}
        onToday={goToday}
        loading={loading}
      />

      {isMobile ? (
        <MobileDayView
          weekDays={weekDays}
          mobileDay={mobileDay}
          setMobileDay={setMobileDay}
          byDay={byDay}
          loading={loading}
          onSelectLesson={setSelectedLesson}
        />
      ) : (
        <WeekGrid
          weekDays={weekDays}
          byDay={byDay}
          hours={hours}
          loading={loading}
          onSelectLesson={setSelectedLesson}
          onSelectSlot={setCreateSlot}
        />
      )}

      {selectedLesson && (
        <LessonDetailsModal
          lesson={selectedLesson}
          onClose={() => setSelectedLesson(null)}
          onDone={handleActionDone}
          onAttendance={id => navigate(`/attendance?lesson=${id}`)}
        />
      )}

      {createSlot && (
        <CreateLessonModal
          slot={createSlot}
          groups={groups}
          rooms={rooms}
          teachers={teachers}
          onClose={() => setCreateSlot(null)}
          onDone={handleActionDone}
        />
      )}
    </div>
  )
}

function CalendarHeader({ weekStart, onPrev, onNext, onToday, loading }) {
  return (
    <div style={{
      background: '#fff', borderRadius: 16, padding: '16px 24px', marginBottom: 16,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
      border: '1px solid #F0F0F5',
    }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Расписание</h1>
        <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{formatWeekRange(weekStart)}{loading ? ' · загрузка…' : ''}</p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button onClick={onPrev} style={navBtnStyle} aria-label="Предыдущая неделя"><ChevronLeft size={16} /></button>
        <button onClick={onToday} style={{ ...navBtnStyle, width: 'auto', padding: '0 16px', fontWeight: 600, fontSize: 13, color: ACCENT }}>Сегодня</button>
        <button onClick={onNext} style={navBtnStyle} aria-label="Следующая неделя"><ChevronRight size={16} /></button>
      </div>
    </div>
  )
}

const navBtnStyle = {
  width: 36, height: 36, borderRadius: 10, border: '1px solid #F0F0F5',
  background: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#6B7280', fontFamily: 'Manrope',
}

function LessonChip({ lesson, style, onClick }) {
  const color = lesson.direction_color || DEFAULT_COLOR
  const isCancelled = lesson.status === 'cancelled'
  const isRescheduled = lesson.status === 'rescheduled'
  const dimmed = isCancelled || isRescheduled

  return (
    <div
      onClick={onClick}
      style={{
        position: 'absolute', ...style,
        background: dimmed ? '#F5F5F7' : `${color}1A`,
        border: `1.5px ${isRescheduled ? 'dashed' : 'solid'} ${dimmed ? '#D1D5DB' : color}`,
        borderRadius: 8, padding: '4px 8px', overflow: 'hidden', cursor: 'pointer',
        opacity: dimmed ? 0.65 : 1,
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
    >
      <div style={{
        fontSize: 11, fontWeight: 700, color: dimmed ? '#9CA3AF' : '#1A1A2E',
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        textDecoration: isCancelled ? 'line-through' : 'none',
      }}>
        {lesson.group_name || 'Индив. занятие'}
      </div>
      <div style={{ fontSize: 10, color: dimmed ? '#9CA3AF' : '#6B7280', whiteSpace: 'nowrap' }}>
        {localTimePart(lesson.starts_at_local)}–{localTimePart(lesson.ends_at_local)}
        {lesson.capacity != null && ` · ${lesson.enrolled_count}/${lesson.capacity}`}
      </div>
      {dimmed && (
        <div style={{ fontSize: 9, fontWeight: 700, color: isCancelled ? '#DC2626' : '#D97706', marginTop: 2 }}>
          {isCancelled ? 'ОТМЕНЕНО' : 'ПЕРЕНЕСЕНО'}
        </div>
      )}
    </div>
  )
}

function WeekGrid({ weekDays, byDay, hours, loading, onSelectLesson, onSelectSlot }) {
  const gridStartHour = hours[0] ?? 8
  const totalHeight = hours.length * ROW_HEIGHT

  function minutesToTop(min) { return ((min - gridStartHour * 60) / 60) * ROW_HEIGHT }

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '56px repeat(7, 1fr)', borderBottom: '1px solid #F0F0F5' }}>
        <div />
        {weekDays.map(day => (
          <div key={toISODate(day)} style={{
            padding: '10px 8px', textAlign: 'center', borderLeft: '1px solid #F0F0F5',
            background: isToday(day) ? '#FDF0EE' : 'transparent',
          }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase' }}>
              {WEEKDAY_LABELS[day.getDay() === 0 ? 6 : day.getDay() - 1]}
            </div>
            <div style={{ fontSize: 15, fontWeight: 700, color: isToday(day) ? ACCENT : '#1A1A2E' }}>
              {day.getDate()}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '56px repeat(7, 1fr)', position: 'relative', maxHeight: '70vh', overflowY: 'auto' }}>
        <div>
          {hours.map(h => (
            <div key={h} style={{ height: ROW_HEIGHT, textAlign: 'right', paddingRight: 8, paddingTop: 4, boxSizing: 'border-box', fontSize: 11, color: '#9CA3AF' }}>
              {String(h).padStart(2, '0')}:00
            </div>
          ))}
        </div>
        {weekDays.map(day => {
          const dateStr = toISODate(day)
          const dayLessons = byDay[dateStr] || []
          return (
            <div key={dateStr} style={{ position: 'relative', borderLeft: '1px solid #F0F0F5', height: totalHeight }}>
              {hours.map((h, i) => (
                <div
                  key={h}
                  onClick={() => onSelectSlot({ date: dateStr, time: `${String(h).padStart(2, '0')}:00` })}
                  style={{ position: 'absolute', top: i * ROW_HEIGHT, left: 0, right: 0, height: ROW_HEIGHT, borderBottom: '1px solid #F7F7FA', cursor: 'pointer' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#FAFAFA'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                />
              ))}
              {dayLessons.map(lesson => (
                <LessonChip
                  key={lesson.id}
                  lesson={lesson}
                  onClick={e => { e.stopPropagation(); onSelectLesson(lesson) }}
                  style={{
                    top: minutesToTop(lesson.startMin) + 1,
                    height: Math.max(minutesToTop(lesson.endMin) - minutesToTop(lesson.startMin) - 2, 22),
                    left: `calc(${(lesson.col / lesson.totalCols) * 100}% + 2px)`,
                    width: `calc(${(1 / lesson.totalCols) * 100}% - 4px)`,
                    zIndex: 1,
                  }}
                />
              ))}
            </div>
          )
        })}
      </div>

      {!loading && Object.values(byDay).every(d => d.length === 0) && (
        <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
          На этой неделе занятий нет. Кликните по пустому слоту, чтобы создать.
        </div>
      )}
    </div>
  )
}

function MobileDayView({ weekDays, mobileDay, setMobileDay, byDay, loading, onSelectLesson }) {
  const day = weekDays[mobileDay]
  const dateStr = toISODate(day)
  const dayLessons = (byDay[dateStr] || []).slice().sort((a, b) => a.startMin - b.startMin)

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', overflow: 'hidden' }}>
      <div style={{ display: 'flex', overflowX: 'auto', borderBottom: '1px solid #F0F0F5' }}>
        {weekDays.map((d, i) => {
          const active = i === mobileDay
          return (
            <button
              key={i}
              onClick={() => setMobileDay(i)}
              style={{
                flex: '1 0 13%', minWidth: 0, padding: '10px 4px', border: 'none', cursor: 'pointer',
                background: active ? '#FDF0EE' : '#fff',
                borderBottom: active ? `2px solid ${ACCENT}` : '2px solid transparent',
                fontFamily: 'Manrope',
              }}
            >
              <div style={{ fontSize: 10, fontWeight: 600, color: active ? ACCENT : '#9CA3AF', textTransform: 'uppercase' }}>
                {WEEKDAY_LABELS[i]}
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: active ? ACCENT : '#1A1A2E' }}>{d.getDate()}</div>
            </button>
          )
        })}
      </div>

      <div style={{ padding: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', marginBottom: 10 }}>{formatDayLabel(day)}</div>
        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка…</div>
        ) : dayLessons.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Занятий нет</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {dayLessons.map(lesson => {
              const color = lesson.direction_color || DEFAULT_COLOR
              const dimmed = lesson.status === 'cancelled' || lesson.status === 'rescheduled'
              return (
                <div
                  key={lesson.id}
                  onClick={() => onSelectLesson(lesson)}
                  style={{
                    display: 'flex', gap: 12, padding: '12px 14px', borderRadius: 12, cursor: 'pointer',
                    border: `1px solid ${dimmed ? '#E5E7EB' : color}`,
                    background: dimmed ? '#FAFAFA' : `${color}0D`,
                    opacity: dimmed ? 0.7 : 1,
                  }}
                >
                  <div style={{ minWidth: 52, fontSize: 13, fontWeight: 700, color: '#1A1A2E' }}>
                    {localTimePart(lesson.starts_at_local)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', textDecoration: lesson.status === 'cancelled' ? 'line-through' : 'none' }}>
                      {lesson.group_name || 'Индив. занятие'}
                    </div>
                    <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>
                      {lesson.room_name || '—'} · {lesson.teacher_name || '—'}
                      {lesson.capacity != null && ` · ${lesson.enrolled_count}/${lesson.capacity}`}
                    </div>
                    {dimmed && (
                      <div style={{ fontSize: 10, fontWeight: 700, color: lesson.status === 'cancelled' ? '#DC2626' : '#D97706', marginTop: 4 }}>
                        {STATUS_LABEL[lesson.status]}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

const modalOverlay = { position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }
const modalBox = { background: '#fff', borderRadius: 16, width: '100%', maxWidth: 420, padding: '24px 24px 20px', fontFamily: 'Manrope' }
const primaryBtn = { padding: '10px 18px', border: 'none', borderRadius: 8, background: `linear-gradient(135deg, #E8998D, ${ACCENT})`, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }
const secondaryBtn = { padding: '10px 18px', border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }
const dangerBtn = { ...secondaryBtn, color: '#DC2626', borderColor: '#FECACA' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box' }
const labelStyle = { display: 'block', fontSize: 11, fontWeight: 600, color: '#9CA3AF', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }

function LessonDetailsModal({ lesson, onClose, onDone, onAttendance }) {
  const [mode, setMode] = useState('view') // view | cancel | reschedule
  const [reason, setReason] = useState('')
  const [newDate, setNewDate] = useState(localDatePart(lesson.starts_at_local))
  const [newTime, setNewTime] = useState(localTimePart(lesson.starts_at_local))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const canAct = lesson.status === 'scheduled'
  const durationMs = new Date(lesson.ends_at) - new Date(lesson.starts_at)

  async function handleCancel() {
    setSaving(true); setError('')
    try {
      await cancelLesson(lesson.id, reason)
      onDone()
    } catch (e) { setError(e.response?.data?.detail || 'Не удалось отменить занятие') }
    finally { setSaving(false) }
  }

  async function handleReschedule() {
    setSaving(true); setError('')
    try {
      const startsAt = new Date(`${newDate}T${newTime}:00`)
      const endsAt = new Date(startsAt.getTime() + durationMs)
      await rescheduleLesson(lesson.id, {
        group: lesson.group,
        room: lesson.room,
        teacher: lesson.teacher,
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
      })
      onDone()
    } catch (e) { setError(e.response?.data?.detail || 'Не удалось перенести занятие') }
    finally { setSaving(false) }
  }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>{lesson.group_name || 'Индив. занятие'}</h2>
            <p style={{ fontSize: 12, color: '#9CA3AF', margin: '4px 0 0' }}>{STATUS_LABEL[lesson.status]}</p>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        {mode === 'view' && (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              <InfoRow icon={<MapPin size={14} />} text={`${localTimePart(lesson.starts_at_local)}–${localTimePart(lesson.ends_at_local)} · ${lesson.room_name || 'зал не указан'}`} />
              <InfoRow icon={<UserIcon size={14} />} text={lesson.teacher_name || 'преподаватель не назначен'} />
              {lesson.capacity != null && (
                <InfoRow icon={<Users size={14} />} text={`${lesson.enrolled_count} из ${lesson.capacity} записано`} />
              )}
              {lesson.status === 'cancelled' && lesson.cancel_reason && (
                <div style={{ fontSize: 12, color: '#DC2626', background: '#FEF2F2', borderRadius: 8, padding: '8px 10px' }}>
                  Причина отмены: {lesson.cancel_reason}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button style={primaryBtn} onClick={() => onAttendance(lesson.id)}>Отметить посещаемость</button>
              {canAct && (
                <>
                  <button style={secondaryBtn} onClick={() => setMode('reschedule')}>Перенести</button>
                  <button style={dangerBtn} onClick={() => setMode('cancel')}>Отменить занятие</button>
                </>
              )}
            </div>
          </>
        )}

        {mode === 'cancel' && (
          <div>
            <label style={labelStyle}>Причина отмены</label>
            <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} style={{ ...inputStyle, marginBottom: 14, resize: 'vertical' }} placeholder="Необязательно" />
            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 10 }}>{error}</p>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button style={secondaryBtn} onClick={() => setMode('view')}>Назад</button>
              <button style={{ ...dangerBtn, background: '#DC2626', color: '#fff', borderColor: '#DC2626' }} disabled={saving} onClick={handleCancel}>
                {saving ? 'Отмена…' : 'Подтвердить отмену'}
              </button>
            </div>
          </div>
        )}

        {mode === 'reschedule' && (
          <div>
            <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Дата</label>
                <input type="date" value={newDate} onChange={e => setNewDate(e.target.value)} style={inputStyle} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>Время</label>
                <input type="time" value={newTime} onChange={e => setNewTime(e.target.value)} style={inputStyle} />
              </div>
            </div>
            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 10 }}>{error}</p>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button style={secondaryBtn} onClick={() => setMode('view')}>Назад</button>
              <button style={primaryBtn} disabled={saving} onClick={handleReschedule}>
                {saving ? 'Перенос…' : 'Перенести'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function InfoRow({ icon, text }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: '#374151' }}>
      <span style={{ color: '#9CA3AF', flexShrink: 0, display: 'flex' }}>{icon}</span>
      {text}
    </div>
  )
}

function CreateLessonModal({ slot, groups, rooms, teachers, onClose, onDone }) {
  const [groupId, setGroupId] = useState('')
  const [roomId, setRoomId] = useState('')
  const [teacherId, setTeacherId] = useState('')
  const [time, setTime] = useState(slot.time)
  const [durationMin, setDurationMin] = useState(60)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (!groupId) { setError('Выберите группу'); return }
    setSaving(true); setError('')
    try {
      const startsAt = new Date(`${slot.date}T${time}:00`)
      const endsAt = new Date(startsAt.getTime() + durationMin * 60000)
      await createLesson({
        group: groupId,
        room: roomId || null,
        teacher: teacherId || null,
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
      })
      onDone()
    } catch (e2) { setError(e2.response?.data?.detail || 'Не удалось создать занятие') }
    finally { setSaving(false) }
  }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Новое занятие</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 12 }}>
            <label style={labelStyle}>Группа *</label>
            <select value={groupId} onChange={e => setGroupId(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
              <option value="">Выберите группу</option>
              {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Дата</label>
              <input type="date" value={slot.date} disabled style={{ ...inputStyle, background: '#FAFAFA', color: '#9CA3AF' }} />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Время</label>
              <input type="time" value={time} onChange={e => setTime(e.target.value)} style={inputStyle} />
            </div>
            <div style={{ width: 90 }}>
              <label style={labelStyle}>Мин.</label>
              <input type="number" min={15} step={15} value={durationMin} onChange={e => setDurationMin(Number(e.target.value))} style={inputStyle} />
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Зал</label>
              <select value={roomId} onChange={e => setRoomId(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
                <option value="">—</option>
                {rooms.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Преподаватель</label>
              <select value={teacherId} onChange={e => setTeacherId(e.target.value)} style={{ ...inputStyle, cursor: 'pointer' }}>
                <option value="">—</option>
                {teachers.map(t => <option key={t.id} value={t.id}>{t.full_name}</option>)}
              </select>
            </div>
          </div>
          {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{error}</p>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" style={secondaryBtn} onClick={onClose}>Отмена</button>
            <button type="submit" style={primaryBtn} disabled={saving}>
              {saving ? 'Создание…' : (<><Plus size={14} style={{ marginRight: 4, verticalAlign: -2 }} />Создать</>)}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
