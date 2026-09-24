import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ChevronLeft, ChevronRight, ChevronDown, Check, X, Users, MapPin, User as UserIcon,
  Plus, CalendarDays, Rows3, AlertTriangle,
} from 'lucide-react'
import {
  startOfWeek, addDays, toISODate, isToday, formatWeekRange, formatDayLabel,
  localDatePart, localTimePart, timeToMinutes, WEEKDAY_LABELS,
} from '../utils/calendarDate'
import {
  fetchLessons, fetchGroups, fetchRooms, fetchTeachers, fetchBranches, fetchDirections, fetchMe,
  fetchConflicts, searchChildren, createLesson, cancelLesson, rescheduleLesson,
} from '../api/lessons'

const ACCENT = '#C97B6E'
const DEFAULT_COLOR = '#7C6FF7'
const ROW_HEIGHT = 56 // px за час
const MOBILE_BREAKPOINT = 860
const FILTERS_STORAGE_KEY = 'kidscrm.schedule.filters'
const EMPTY_FILTERS = { branch: '', room: '', teacher: '', direction: '' }

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

function loadStoredFilters() {
  try {
    const raw = localStorage.getItem(FILTERS_STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch { return {} }
}

function saveStoredFilters(view, filters) {
  try { localStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify({ view, ...filters })) } catch { /* приватный режим и т.п. — не критично */ }
}

// Раскладка занятий одного столбца (день недели, либо зал в дневном виде)
// по колонкам, чтобы пересекающиеся по времени не наезжали друг на друга
// (простой greedy-алгоритм интервального графа).
function layoutColumn(lessons) {
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

function withMinutes(lesson) {
  return {
    ...lesson,
    startMin: timeToMinutes(localTimePart(lesson.starts_at_local)),
    endMin: timeToMinutes(localTimePart(lesson.ends_at_local)),
  }
}

// TRU-47: у индивидуального занятия нет group_name — заголовок вместо
// generic "Индив. занятие" показывает, для кого оно.
function lessonTitle(lesson) {
  if (lesson.group_name) return lesson.group_name
  if (lesson.is_individual && lesson.individual_children_names?.length) {
    return lesson.individual_children_names.join(', ')
  }
  return 'Индив. занятие'
}

function computeHourRange(lessons) {
  let min = 8, max = 21
  lessons.forEach(l => {
    const startH = Math.floor(l.startMin / 60)
    const endH = Math.ceil(l.endMin / 60)
    if (startH < min) min = startH
    if (endH > max) max = endH
  })
  return Array.from({ length: max - min }, (_, i) => min + i)
}

export default function Schedule() {
  const [searchParams, setSearchParams] = useSearchParams()
  const stored = useMemo(loadStoredFilters, [])

  const [view, setView] = useState(() => searchParams.get('view') || stored.view || 'week')
  const [date, setDate] = useState(() => searchParams.get('date') || toISODate(new Date()))
  const [filters, setFilters] = useState(() => ({
    branch: searchParams.get('branch') || stored.branch || '',
    room: searchParams.get('room') || stored.room || '',
    teacher: searchParams.get('teacher') || stored.teacher || '',
    direction: searchParams.get('direction') || stored.direction || '',
  }))

  const [me, setMe] = useState(null)
  const [lessons, setLessons] = useState([])
  const [loading, setLoading] = useState(true)
  const [groups, setGroups] = useState([])
  const [rooms, setRooms] = useState([])
  const [teachers, setTeachers] = useState([])
  const [branches, setBranches] = useState([])
  const [directions, setDirections] = useState([])
  const [selectedLesson, setSelectedLesson] = useState(null)
  const [createSlot, setCreateSlot] = useState(null)
  const [mobileDay, setMobileDay] = useState(0)
  const [conflictsCount, setConflictsCount] = useState(0)
  const [showConflicts, setShowConflicts] = useState(false)
  const isMobile = useIsMobile()
  const navigate = useNavigate()
  const isTeacher = me?.role === 'teacher'

  const weekStart = useMemo(() => startOfWeek(new Date(date)), [date])
  const weekDays = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(weekStart, i)), [weekStart])

  // Фильтры и вид — в URL (переживают шаринг ссылки и обновление страницы)
  // и в localStorage (переживают закрытие вкладки). Дата в localStorage не
  // хранится — новая сессия без даты в URL открывается на сегодня.
  useEffect(() => {
    const next = new URLSearchParams(searchParams)
    next.set('view', view)
    next.set('date', date)
    Object.entries(filters).forEach(([key, value]) => {
      if (value) next.set(key, value); else next.delete(key)
    })
    setSearchParams(next, { replace: true })
    saveStoredFilters(view, filters)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, date, filters])

  const load = useCallback(() => {
    setLoading(true)
    const from = view === 'week' ? toISODate(weekStart) : date
    const to = view === 'week' ? toISODate(addDays(weekStart, 6)) : date
    fetchLessons(from, to, filters)
      .then(setLessons)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [view, date, weekStart, filters])

  useEffect(() => { load() }, [load])

  const loadConflicts = useCallback(() => {
    fetchConflicts(filters).then(list => setConflictsCount(list.length)).catch(console.error)
  }, [filters])

  useEffect(() => { loadConflicts() }, [loadConflicts])

  useEffect(() => {
    fetchMe().then(setMe).catch(console.error)
    fetchGroups().then(setGroups).catch(console.error)
    fetchRooms().then(setRooms).catch(console.error)
    fetchBranches().then(setBranches).catch(console.error)
    fetchDirections().then(setDirections).catch(console.error)
  }, [])

  useEffect(() => {
    // Преподавателю бэкенд и так отдаёт только его занятия (TRU-19) —
    // список остальных преподавателей ему не нужен.
    if (isTeacher) { setTeachers([]); return }
    fetchTeachers().then(setTeachers).catch(console.error)
  }, [isTeacher])

  const filteredRooms = useMemo(
    () => filters.branch ? rooms.filter(r => String(r.branch) === String(filters.branch)) : rooms,
    [rooms, filters.branch]
  )

  const byWeekday = useMemo(() => {
    const map = {}
    weekDays.forEach(d => { map[toISODate(d)] = [] })
    lessons.forEach(lesson => {
      const dateStr = localDatePart(lesson.starts_at_local)
      if (!(dateStr in map)) return
      map[dateStr].push(withMinutes(lesson))
    })
    Object.keys(map).forEach(k => { map[k] = layoutColumn(map[k]) })
    return map
  }, [lessons, weekDays])

  const byRoom = useMemo(() => {
    const map = {}
    lessons.forEach(lesson => {
      const key = lesson.room || '__none__'
      if (!map[key]) map[key] = []
      map[key].push(withMinutes(lesson))
    })
    Object.keys(map).forEach(k => { map[k] = layoutColumn(map[k]) })
    return map
  }, [lessons])

  const dayColumns = useMemo(() => {
    const cols = filteredRooms.map(r => ({ id: r.id, name: r.name }))
    if (byRoom.__none__?.length) cols.push({ id: '__none__', name: 'Без зала' })
    return cols
  }, [filteredRooms, byRoom])

  const hours = useMemo(
    () => computeHourRange(view === 'week' ? lessons.map(withMinutes) : lessons.map(withMinutes)),
    [lessons, view]
  )

  function goToday() {
    const today = new Date()
    setDate(toISODate(today))
    setMobileDay(today.getDay() === 0 ? 6 : today.getDay() - 1)
  }
  function goPrev() { setDate(d => toISODate(addDays(new Date(d), view === 'week' ? -7 : -1))) }
  function goNext() { setDate(d => toISODate(addDays(new Date(d), view === 'week' ? 7 : 1))) }

  function handleActionDone() { setSelectedLesson(null); setCreateSlot(null); load(); loadConflicts() }

  const headerLabel = view === 'week' ? formatWeekRange(weekStart) : formatDayLabel(new Date(date))

  return (
    <div>
      <CalendarHeader
        label={headerLabel}
        view={view}
        onViewChange={setView}
        onPrev={goPrev}
        onNext={goNext}
        onToday={goToday}
        loading={loading}
        conflictsCount={conflictsCount}
        onShowConflicts={() => setShowConflicts(true)}
      />

      <FiltersBar
        filters={filters}
        onChange={patch => setFilters(f => ({ ...f, ...patch }))}
        onReset={() => setFilters(EMPTY_FILTERS)}
        branches={branches}
        rooms={filteredRooms}
        teachers={teachers}
        directions={directions}
        isTeacher={isTeacher}
      />

      {view === 'week' && (
        isMobile ? (
          <MobileWeekDayView
            weekDays={weekDays}
            mobileDay={mobileDay}
            setMobileDay={setMobileDay}
            byDay={byWeekday}
            loading={loading}
            onSelectLesson={setSelectedLesson}
          />
        ) : (
          <WeekGrid
            weekDays={weekDays}
            byDay={byWeekday}
            hours={hours}
            loading={loading}
            onSelectLesson={setSelectedLesson}
            onSelectSlot={isTeacher ? undefined : setCreateSlot}
          />
        )
      )}

      {view === 'day' && (
        isMobile ? (
          <MobileDayRoomsView
            date={date}
            columns={dayColumns}
            byRoom={byRoom}
            loading={loading}
            onSelectLesson={setSelectedLesson}
          />
        ) : (
          <DayGrid
            date={date}
            columns={dayColumns}
            byRoom={byRoom}
            hours={hours}
            loading={loading}
            onSelectLesson={setSelectedLesson}
            onSelectSlot={isTeacher ? undefined : setCreateSlot}
          />
        )
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

      {showConflicts && (
        <ConflictsModal
          filters={filters}
          onClose={() => setShowConflicts(false)}
          onSelectLesson={lesson => { setShowConflicts(false); setSelectedLesson(lesson) }}
        />
      )}
    </div>
  )
}

function CalendarHeader({ label, view, onViewChange, onPrev, onNext, onToday, loading, conflictsCount, onShowConflicts }) {
  return (
    <div style={{
      background: '#fff', borderRadius: 16, padding: '16px 24px', marginBottom: 16,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
      border: '1px solid #F0F0F5',
    }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Расписание</h1>
        <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{label}{loading ? ' · загрузка…' : ''}</p>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {conflictsCount > 0 && (
          <button
            onClick={onShowConflicts}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '0 14px', height: 36,
              border: '1.5px solid #FDE68A', borderRadius: 10, background: '#FFFBEB', color: '#B45309',
              fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
            }}
          >
            <AlertTriangle size={14} /> Конфликты ({conflictsCount})
          </button>
        )}
        <div style={{ display: 'flex', background: '#F8F9FF', borderRadius: 10, padding: 3, gap: 2 }}>
          <ViewToggleBtn active={view === 'week'} onClick={() => onViewChange('week')} icon={<Rows3 size={14} />} label="Неделя" />
          <ViewToggleBtn active={view === 'day'} onClick={() => onViewChange('day')} icon={<CalendarDays size={14} />} label="День" />
        </div>
        <button onClick={onPrev} style={navBtnStyle} aria-label="Назад"><ChevronLeft size={16} /></button>
        <button onClick={onToday} style={{ ...navBtnStyle, width: 'auto', padding: '0 16px', fontWeight: 600, fontSize: 13, color: ACCENT }}>Сегодня</button>
        <button onClick={onNext} style={navBtnStyle} aria-label="Вперёд"><ChevronRight size={16} /></button>
      </div>
    </div>
  )
}

function ViewToggleBtn({ active, onClick, icon, label }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', border: 'none', borderRadius: 8,
        background: active ? '#fff' : 'transparent', color: active ? ACCENT : '#6B7280',
        fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
        boxShadow: active ? '0 1px 3px rgba(0,0,0,0.08)' : 'none',
      }}
    >
      {icon}{label}
    </button>
  )
}

const navBtnStyle = {
  width: 36, height: 36, borderRadius: 10, border: '1px solid #F0F0F5',
  background: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
  color: '#6B7280', fontFamily: 'Manrope',
}

// options: [[value, label], ...], value === '' — пункт по умолчанию ("Все…")
// options: [[value, label], ...], value === '' — пункт по умолчанию.
// variant 'filter' — компактный чип для панели фильтров (подсвечивается,
// когда выбрано не значение по умолчанию); 'field' — обычное поле формы
// в модалках (тот же вид, что inputStyle/select у соседних инпутов).
function Dropdown({ value, onChange, options, width = 160, variant = 'filter', placeholder }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selected = options.find(([v]) => v === value)
  const active = variant === 'filter' && value !== ''
  const displayText = selected ? selected[1] : (placeholder ?? options[0][1])

  return (
    <div ref={ref} style={{ width, flexShrink: 0, position: 'relative' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', boxSizing: 'border-box',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: variant === 'field' ? '9px 12px' : '8px 12px',
          border: `1.5px solid ${open || active ? ACCENT : '#EBEBF0'}`,
          borderRadius: 8,
          background: active ? '#FDF0EE' : (variant === 'field' ? '#fff' : '#FAFAFA'),
          fontSize: variant === 'field' ? 13 : 12,
          fontFamily: 'Manrope', fontWeight: active ? 600 : 400,
          color: active ? ACCENT : (variant === 'field' ? '#1A1A2E' : '#6B7280'),
          cursor: 'pointer', outline: 'none',
          transition: 'border-color 0.15s, background 0.15s',
          boxShadow: open ? `0 0 0 3px ${ACCENT}1F` : 'none',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {displayText}
        </span>
        <ChevronDown
          size={13}
          style={{ flexShrink: 0, marginLeft: 6, color: active ? ACCENT : '#9CA3AF',
            transform: open ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
        />
      </button>

      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 100,
          background: '#fff',
          border: '1.5px solid #F0F0F5',
          borderRadius: 10,
          boxShadow: '0 8px 24px rgba(0,0,0,0.10)',
          overflow: 'hidden',
          maxHeight: 260, overflowY: 'auto',
        }}>
          {options.map(([v, l]) => {
            const isSelected = value === v
            return (
              <div
                key={v}
                onClick={() => { onChange(v); setOpen(false) }}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '9px 12px',
                  fontSize: 12, fontFamily: 'Manrope',
                  fontWeight: isSelected ? 600 : 400,
                  color: isSelected ? ACCENT : '#374151',
                  background: isSelected ? '#FDF0EE' : '#fff',
                  cursor: 'pointer', whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = '#FAFAFA' }}
                onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '#fff' }}
              >
                {l}
                {isSelected && <Check size={12} style={{ color: ACCENT, flexShrink: 0, marginLeft: 8 }} />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function FiltersBar({ filters, onChange, onReset, branches, rooms, teachers, directions, isTeacher }) {
  const hasActive = Object.values(filters).some(Boolean)

  return (
    <div style={{
      background: '#fff', borderRadius: 14, border: '1px solid #F0F0F5', padding: '12px 16px',
      marginBottom: 16, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', overflow: 'visible',
    }}>
      <Dropdown
        value={filters.branch}
        onChange={v => onChange({ branch: v, room: '' })}
        options={[['', 'Все филиалы'], ...branches.map(b => [String(b.id), b.name])]}
      />
      <Dropdown
        value={filters.room}
        onChange={v => onChange({ room: v })}
        options={[['', 'Все залы'], ...rooms.map(r => [String(r.id), r.name])]}
      />
      <Dropdown
        value={filters.direction}
        onChange={v => onChange({ direction: v })}
        options={[['', 'Все направления'], ...directions.map(d => [String(d.id), d.name])]}
      />
      {isTeacher ? (
        <span style={{ fontSize: 12, color: ACCENT, fontWeight: 600, background: '#FDF0EE', padding: '8px 12px', borderRadius: 8 }}>
          Показано ваше расписание
        </span>
      ) : (
        <Dropdown
          value={filters.teacher}
          onChange={v => onChange({ teacher: v })}
          options={[['', 'Все преподаватели'], ...teachers.map(t => [String(t.id), t.full_name])]}
          width={180}
        />
      )}
      {hasActive && (
        <button
          onClick={onReset}
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '8px 12px', border: 'none', background: 'none', color: '#9CA3AF', fontSize: 12, fontFamily: 'Manrope', cursor: 'pointer' }}
        >
          <X size={12} /> Сбросить
        </button>
      )}
    </div>
  )
}

function LessonChip({ lesson, style, onClick }) {
  const color = lesson.direction_color || DEFAULT_COLOR
  const isCancelled = lesson.status === 'cancelled'
  const isRescheduled = lesson.status === 'rescheduled'
  const dimmed = isCancelled || isRescheduled
  // Конфликт (TRU-46) — предупреждение, не запрет: занятие остаётся видно
  // как обычно, просто с жёлтой рамкой/значком, а не перечёркнуто/сером.
  const hasConflict = lesson.has_conflict && !dimmed
  // Индивидуальное (TRU-47) — визуально отличимо от группового: точечная
  // рамка + иконка человека вместо цвета направления (у него его просто
  // нет — direction приходит через группу).
  const isIndividual = lesson.is_individual && !dimmed && !hasConflict

  return (
    <div
      onClick={onClick}
      style={{
        position: 'absolute', ...style,
        background: dimmed ? '#F5F5F7' : hasConflict ? '#FFFBEB' : `${color}1A`,
        border: `1.5px ${isRescheduled ? 'dashed' : isIndividual ? 'dotted' : 'solid'} ${dimmed ? '#D1D5DB' : hasConflict ? '#F59E0B' : color}`,
        borderRadius: 8, padding: '4px 8px', overflow: 'hidden', cursor: 'pointer',
        opacity: dimmed ? 0.65 : 1,
        transition: 'box-shadow 0.15s',
      }}
      onMouseEnter={e => e.currentTarget.style.boxShadow = '0 2px 8px rgba(0,0,0,0.12)'}
      onMouseLeave={e => e.currentTarget.style.boxShadow = 'none'}
      title={hasConflict ? 'Пересекается по залу или преподавателю с другим занятием' : undefined}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {hasConflict && <AlertTriangle size={10} style={{ color: '#B45309', flexShrink: 0 }} />}
        {isIndividual && <UserIcon size={9} style={{ color, flexShrink: 0 }} />}
        <div style={{
          fontSize: 11, fontWeight: 700, color: dimmed ? '#9CA3AF' : '#1A1A2E',
          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          textDecoration: isCancelled ? 'line-through' : 'none',
        }}>
          {lessonTitle(lesson)}
        </div>
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
      {hasConflict && (
        <div style={{ fontSize: 9, fontWeight: 700, color: '#B45309', marginTop: 2 }}>КОНФЛИКТ</div>
      )}
    </div>
  )
}

// Общая временная сетка (колонки + часы слева) — переиспользуется недельным
// видом (колонки = дни) и дневным видом (колонки = залы).
function TimeGrid({ columns, columnHeader, itemsByColumn, hours, loading, emptyText, onSelectLesson, onSelectSlot }) {
  const gridStartHour = hours[0] ?? 8
  const totalHeight = hours.length * ROW_HEIGHT
  const templateColumns = `56px repeat(${columns.length || 1}, 1fr)`

  function minutesToTop(min) { return ((min - gridStartHour * 60) / 60) * ROW_HEIGHT }

  const isEmpty = !loading && columns.every(c => !(itemsByColumn[c.id]?.length))

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: templateColumns, borderBottom: '1px solid #F0F0F5' }}>
        <div />
        {columns.map(col => (
          <div key={col.id} style={{ padding: '10px 8px', textAlign: 'center', borderLeft: '1px solid #F0F0F5', background: col.highlighted ? '#FDF0EE' : 'transparent' }}>
            {columnHeader(col)}
          </div>
        ))}
      </div>

      {columns.length === 0 ? (
        <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
          Нет залов, подходящих под фильтр.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: templateColumns, position: 'relative', maxHeight: '70vh', overflowY: 'auto' }}>
          <div>
            {hours.map(h => (
              <div key={h} style={{ height: ROW_HEIGHT, textAlign: 'right', paddingRight: 8, paddingTop: 4, boxSizing: 'border-box', fontSize: 11, color: '#9CA3AF' }}>
                {String(h).padStart(2, '0')}:00
              </div>
            ))}
          </div>
          {columns.map(col => {
            const items = itemsByColumn[col.id] || []
            return (
              <div key={col.id} style={{ position: 'relative', borderLeft: '1px solid #F0F0F5', height: totalHeight }}>
                {hours.map((h, i) => (
                  <div
                    key={h}
                    onClick={() => onSelectSlot?.({ col, time: `${String(h).padStart(2, '0')}:00` })}
                    style={{ position: 'absolute', top: i * ROW_HEIGHT, left: 0, right: 0, height: ROW_HEIGHT, borderBottom: '1px solid #F7F7FA', cursor: onSelectSlot ? 'pointer' : 'default' }}
                    onMouseEnter={e => { if (onSelectSlot) e.currentTarget.style.background = '#FAFAFA' }}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  />
                ))}
                {items.map(lesson => (
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
      )}

      {isEmpty && columns.length > 0 && (
        <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{emptyText}</div>
      )}
    </div>
  )
}

function WeekGrid({ weekDays, byDay, hours, loading, onSelectLesson, onSelectSlot }) {
  const columns = weekDays.map(day => ({ id: toISODate(day), day, highlighted: isToday(day) }))
  return (
    <TimeGrid
      columns={columns}
      columnHeader={col => (
        <>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase' }}>
            {WEEKDAY_LABELS[col.day.getDay() === 0 ? 6 : col.day.getDay() - 1]}
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: col.highlighted ? ACCENT : '#1A1A2E' }}>{col.day.getDate()}</div>
        </>
      )}
      itemsByColumn={byDay}
      hours={hours}
      loading={loading}
      emptyText="На этой неделе занятий нет. Кликните по пустому слоту, чтобы создать."
      onSelectLesson={onSelectLesson}
      onSelectSlot={onSelectSlot ? (slot => onSelectSlot({ date: slot.col.id, time: slot.time })) : undefined}
    />
  )
}

function DayGrid({ date, columns, byRoom, hours, loading, onSelectLesson, onSelectSlot }) {
  return (
    <TimeGrid
      columns={columns}
      columnHeader={col => (
        <div style={{ fontSize: 13, fontWeight: 700, color: '#1A1A2E' }}>{col.name}</div>
      )}
      itemsByColumn={byRoom}
      hours={hours}
      loading={loading}
      emptyText="На этот день занятий нет. Кликните по пустому слоту, чтобы создать."
      onSelectLesson={onSelectLesson}
      onSelectSlot={onSelectSlot ? (slot => onSelectSlot({
        date,
        time: slot.time,
        room: slot.col.id === '__none__' ? '' : slot.col.id,
      })) : undefined}
    />
  )
}

function MobileWeekDayView({ weekDays, mobileDay, setMobileDay, byDay, loading, onSelectLesson }) {
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
        <LessonList lessons={dayLessons} loading={loading} emptyText="Занятий нет" onSelectLesson={onSelectLesson} showRoom />
      </div>
    </div>
  )
}

function MobileDayRoomsView({ date, columns, byRoom, loading, onSelectLesson }) {
  const nonEmptyColumns = columns.filter(c => (byRoom[c.id] || []).length > 0)

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', padding: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', marginBottom: 10 }}>{formatDayLabel(new Date(date))}</div>
      {loading ? (
        <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка…</div>
      ) : nonEmptyColumns.length === 0 ? (
        <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>На этот день занятий нет</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {nonEmptyColumns.map(col => (
            <div key={col.id}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', marginBottom: 8 }}>{col.name}</div>
              <LessonList
                lessons={(byRoom[col.id] || []).slice().sort((a, b) => a.startMin - b.startMin)}
                loading={false}
                emptyText=""
                onSelectLesson={onSelectLesson}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function LessonList({ lessons, loading, emptyText, onSelectLesson, showRoom }) {
  if (loading) return <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка…</div>
  if (lessons.length === 0) return emptyText ? <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{emptyText}</div> : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {lessons.map(lesson => {
        const color = lesson.direction_color || DEFAULT_COLOR
        const dimmed = lesson.status === 'cancelled' || lesson.status === 'rescheduled'
        const hasConflict = lesson.has_conflict && !dimmed
        const isIndividual = lesson.is_individual && !dimmed && !hasConflict
        return (
          <div
            key={lesson.id}
            onClick={() => onSelectLesson(lesson)}
            style={{
              display: 'flex', gap: 12, padding: '12px 14px', borderRadius: 12, cursor: 'pointer',
              border: `1px ${isIndividual ? 'dotted' : 'solid'} ${dimmed ? '#E5E7EB' : hasConflict ? '#F59E0B' : color}`,
              background: dimmed ? '#FAFAFA' : hasConflict ? '#FFFBEB' : `${color}0D`,
              opacity: dimmed ? 0.7 : 1,
            }}
          >
            <div style={{ minWidth: 52, fontSize: 13, fontWeight: 700, color: '#1A1A2E' }}>
              {localTimePart(lesson.starts_at_local)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                {hasConflict && <AlertTriangle size={11} style={{ color: '#B45309', flexShrink: 0 }} />}
                {isIndividual && <UserIcon size={11} style={{ color, flexShrink: 0 }} />}
                <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', textDecoration: lesson.status === 'cancelled' ? 'line-through' : 'none' }}>
                  {lessonTitle(lesson)}
                </div>
              </div>
              <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>
                {showRoom && `${lesson.room_name || '—'} · `}{lesson.teacher_name || '—'}
                {lesson.capacity != null && ` · ${lesson.enrolled_count}/${lesson.capacity}`}
              </div>
              {dimmed && (
                <div style={{ fontSize: 10, fontWeight: 700, color: lesson.status === 'cancelled' ? '#DC2626' : '#D97706', marginTop: 4 }}>
                  {STATUS_LABEL[lesson.status]}
                </div>
              )}
              {hasConflict && (
                <div style={{ fontSize: 10, fontWeight: 700, color: '#B45309', marginTop: 4 }}>КОНФЛИКТ ПО ЗАЛУ/ПРЕПОДАВАТЕЛЮ</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ConflictsModal({ filters, onClose, onSelectLesson }) {
  const [conflicts, setConflicts] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchConflicts(filters)
      .then(setConflicts)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [filters])

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={{ ...modalBox, maxWidth: 560, maxHeight: '80vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertTriangle size={16} style={{ color: '#B45309' }} /> Текущие конфликты
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 12, color: '#9CA3AF', margin: '0 0 16px' }}>
          Занятия, которые пересекаются по залу или преподавателю — от сегодня и дальше.
        </p>

        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка…</div>
        ) : conflicts.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Конфликтов нет</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {conflicts.map(lesson => (
              <div
                key={lesson.id}
                onClick={() => onSelectLesson(lesson)}
                style={{
                  display: 'flex', gap: 12, padding: '12px 14px', borderRadius: 10, cursor: 'pointer',
                  border: '1px solid #F59E0B', background: '#FFFBEB',
                }}
              >
                <div style={{ minWidth: 90, fontSize: 12, fontWeight: 700, color: '#1A1A2E' }}>
                  {localDatePart(lesson.starts_at_local).split('-').reverse().join('.')} {localTimePart(lesson.starts_at_local)}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E' }}>{lessonTitle(lesson)}</div>
                  <div style={{ fontSize: 11, color: '#92400E', marginTop: 2 }}>
                    {lesson.room_name || 'без зала'} · {lesson.teacher_name || 'без преподавателя'}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Список занятий, с которыми пересекается создаваемое/переносимое — общий
// вид для CreateLessonModal и LessonDetailsModal (перенос).
function ConflictWarning({ conflicts, onConfirm, onBack, saving }) {
  return (
    <div style={{ background: '#FFFBEB', border: '1.5px solid #FDE68A', borderRadius: 10, padding: '14px 16px', marginBottom: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <AlertTriangle size={15} style={{ color: '#B45309', flexShrink: 0 }} />
        <span style={{ fontSize: 13, fontWeight: 700, color: '#92400E', fontFamily: 'Manrope' }}>
          Пересекается с {conflicts.length === 1 ? 'занятием' : 'занятиями'} по залу или преподавателю
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
        {conflicts.map(c => (
          <div key={c.id} style={{ fontSize: 12, color: '#92400E', fontFamily: 'Manrope' }}>
            {lessonTitle(c)} · {localTimePart(c.starts_at_local)}–{localTimePart(c.ends_at_local)}
            {c.room_name && ` · ${c.room_name}`}{c.teacher_name && ` · ${c.teacher_name}`}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" onClick={onBack} style={secondaryBtn}>Изменить</button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={saving}
          style={{ padding: '10px 18px', border: 'none', borderRadius: 8, background: '#D97706', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}
        >
          {saving ? 'Сохранение…' : 'Всё равно сохранить'}
        </button>
      </div>
    </div>
  )
}

const modalOverlay = { position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }
const modalBox = { background: '#fff', borderRadius: 16, width: '100%', maxWidth: 420, padding: '24px 24px 20px', fontFamily: 'Manrope' }
const primaryBtn = { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '10px 18px', border: 'none', borderRadius: 8, background: `linear-gradient(135deg, #E8998D, ${ACCENT})`, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }
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
  const [conflicts, setConflicts] = useState(null)

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

  async function submitReschedule(extra) {
    setSaving(true); setError('')
    try {
      const startsAt = new Date(`${newDate}T${newTime}:00`)
      const endsAt = new Date(startsAt.getTime() + durationMs)
      await rescheduleLesson(lesson.id, {
        group: lesson.group,
        // TRU-47: у переносимого индивидуального занятия участники не
        // берутся автоматически — новое занятие создаётся с нуля, нужно
        // явно перенести тех же детей.
        individual_children: lesson.is_individual ? lesson.individual_children : [],
        room: lesson.room,
        teacher: lesson.teacher,
        starts_at: startsAt.toISOString(),
        ends_at: endsAt.toISOString(),
        ...extra,
      })
      onDone()
    } catch (e) {
      if (e.response?.status === 409) {
        setConflicts(e.response.data.conflicts)
      } else {
        setError(e.response?.data?.detail || 'Не удалось перенести занятие')
      }
    } finally { setSaving(false) }
  }

  function handleReschedule() { submitReschedule() }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
          <div>
            <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
              {lesson.is_individual && <UserIcon size={15} style={{ color: DEFAULT_COLOR }} />}
              {lessonTitle(lesson)}
            </h2>
            <p style={{ fontSize: 12, color: '#9CA3AF', margin: '4px 0 0' }}>
              {lesson.is_individual ? 'Индивидуальное занятие' : 'Групповое занятие'} · {STATUS_LABEL[lesson.status]}
            </p>
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
              {lesson.is_individual && (
                <InfoRow icon={<Users size={14} />} text={lesson.individual_children_names?.length ? lesson.individual_children_names.join(', ') : 'дети не указаны'} />
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
            {conflicts && (
              <ConflictWarning
                conflicts={conflicts}
                saving={saving}
                onBack={() => setConflicts(null)}
                onConfirm={() => submitReschedule({ confirm_conflict: true })}
              />
            )}
            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 10 }}>{error}</p>}
            {!conflicts && (
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button style={secondaryBtn} onClick={() => setMode('view')}>Назад</button>
                <button style={primaryBtn} disabled={saving} onClick={handleReschedule}>
                  {saving ? 'Перенос…' : 'Перенести'}
                </button>
              </div>
            )}
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

// Поиск + мультивыбор детей для индивидуального занятия (TRU-47).
// value: [{id, full_name}]
function ChildrenMultiSelect({ value, onChange }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const debounceRef = useRef()

  useEffect(() => {
    if (!query.trim()) { setResults([]); return }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      searchChildren(query)
        .then(list => setResults(list.filter(c => !value.some(v => v.id === c.id)).slice(0, 8)))
        .catch(console.error)
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query, value])

  function add(child) {
    onChange([...value, { id: child.id, full_name: child.full_name }])
    setQuery('')
    setResults([])
  }

  function remove(id) {
    onChange(value.filter(c => c.id !== id))
  }

  return (
    <div>
      {value.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
          {value.map(c => (
            <span key={c.id} style={{
              display: 'flex', alignItems: 'center', gap: 5, padding: '4px 8px 4px 10px',
              background: '#FDF0EE', color: ACCENT, borderRadius: 6, fontSize: 12, fontWeight: 600, fontFamily: 'Manrope',
            }}>
              {c.full_name}
              <button type="button" onClick={() => remove(c.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: ACCENT, display: 'flex', padding: 0 }}>
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div style={{ position: 'relative' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Начните вводить имя..."
          style={inputStyle}
        />
        {results.length > 0 && (
          <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 100, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', overflow: 'hidden' }}>
            {results.map(c => (
              <div key={c.id} onClick={() => add(c)}
                style={{ padding: '9px 12px', fontSize: 13, fontFamily: 'Manrope', cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = '#FAFAFA'}
                onMouseLeave={e => e.currentTarget.style.background = '#fff'}
              >
                {c.full_name}{c.age != null && <span style={{ color: '#9CA3AF' }}> · {c.age} лет</span>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function CreateLessonModal({ slot, groups, rooms, teachers, onClose, onDone }) {
  const [lessonType, setLessonType] = useState('group') // group | individual (TRU-47)
  const [groupId, setGroupId] = useState('')
  const [children, setChildren] = useState([]) // [{id, full_name}]
  const [roomId, setRoomId] = useState(slot.room || '')
  const [teacherId, setTeacherId] = useState('')
  const [time, setTime] = useState(slot.time)
  const [durationMin, setDurationMin] = useState(60)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [conflicts, setConflicts] = useState(null)

  function buildPayload(extra) {
    const startsAt = new Date(`${slot.date}T${time}:00`)
    const endsAt = new Date(startsAt.getTime() + durationMin * 60000)
    return {
      group: lessonType === 'group' ? groupId : null,
      individual_children: lessonType === 'individual' ? children.map(c => c.id) : [],
      room: roomId || null,
      teacher: teacherId || null,
      starts_at: startsAt.toISOString(),
      ends_at: endsAt.toISOString(),
      ...extra,
    }
  }

  async function submit(payload) {
    setSaving(true); setError('')
    try {
      await createLesson(payload)
      onDone()
    } catch (e2) {
      if (e2.response?.status === 409) {
        setConflicts(e2.response.data.conflicts)
      } else {
        setError(e2.response?.data?.detail || 'Не удалось создать занятие')
      }
    } finally { setSaving(false) }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (lessonType === 'group' && !groupId) { setError('Выберите группу'); return }
    if (lessonType === 'individual' && children.length === 0) { setError('Выберите хотя бы одного ребёнка'); return }
    submit(buildPayload())
  }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Новое занятие</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ display: 'flex', background: '#F8F9FF', borderRadius: 10, padding: 3, gap: 2, marginBottom: 14 }}>
            <ViewToggleBtn active={lessonType === 'group'} onClick={() => setLessonType('group')} icon={<Users size={14} />} label="Групповое" />
            <ViewToggleBtn active={lessonType === 'individual'} onClick={() => setLessonType('individual')} icon={<UserIcon size={14} />} label="Индивидуальное" />
          </div>

          {lessonType === 'group' ? (
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>Группа *</label>
              <Dropdown
                variant="field"
                width="100%"
                value={groupId}
                onChange={setGroupId}
                placeholder="Выберите группу"
                options={[['', 'Выберите группу'], ...groups.map(g => [String(g.id), g.name])]}
              />
            </div>
          ) : (
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>Ребёнок (или несколько) *</label>
              <ChildrenMultiSelect value={children} onChange={setChildren} />
            </div>
          )}
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
              <Dropdown
                variant="field"
                width="100%"
                value={roomId}
                onChange={setRoomId}
                options={[['', '—'], ...rooms.map(r => [String(r.id), r.name])]}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Преподаватель</label>
              <Dropdown
                variant="field"
                width="100%"
                value={teacherId}
                onChange={setTeacherId}
                options={[['', '—'], ...teachers.map(t => [String(t.id), t.full_name])]}
              />
            </div>
          </div>
          {conflicts && (
            <ConflictWarning
              conflicts={conflicts}
              saving={saving}
              onBack={() => setConflicts(null)}
              onConfirm={() => submit(buildPayload({ confirm_conflict: true }))}
            />
          )}
          {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{error}</p>}
          {!conflicts && (
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" style={secondaryBtn} onClick={onClose}>Отмена</button>
              <button type="submit" style={primaryBtn} disabled={saving}>
                {saving ? 'Создание…' : (<><Plus size={14} />Создать</>)}
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
