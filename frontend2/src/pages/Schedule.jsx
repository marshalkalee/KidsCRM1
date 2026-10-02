import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ChevronLeft, ChevronRight, ChevronDown, Check, X, Users, MapPin, User as UserIcon,
  Plus, CalendarDays, Rows3, AlertTriangle, Ban, Phone, MessageCircle, PhoneCall,
} from 'lucide-react'
import {
  startOfWeek, addDays, toISODate, isToday, formatWeekRange, formatDayLabel,
  localDatePart, localTimePart, timeToMinutes, WEEKDAY_LABELS,
} from '../utils/calendarDate'
import {
  fetchLessons, fetchGroups, fetchRooms, fetchTeachers, fetchBranches, fetchDirections, fetchMe,
  fetchConflicts, searchChildren, createLesson, cancelLesson, bulkCancelLessons, rescheduleLesson,
  fetchWhoToCall, markCalled, unmarkCalled,
} from '../api/lessons'
import { t } from '../i18n'

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

const ENROLLMENT_KIND_UI = {
  trial: { label: 'Пробное', color: '#7C3AED', background: '#F3E8FF', border: '#DDD6FE' },
  makeup: { label: 'Отработка', color: '#2563EB', background: '#EFF6FF', border: '#BFDBFE' },
}

// TRU-48: справочник причин отмены — тот же список, что Lesson.CancelReasonCategory на бэке.
const CANCEL_REASON_OPTIONS = [
  ['teacher_illness', 'Болезнь преподавателя'],
  ['holiday', 'Праздник'],
  ['room_incident', 'Авария в помещении'],
  ['other', 'Другое'],
]

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

// Группирует уже разложенные (layoutColumn) занятия одного дня/зала в
// кластеры по фактическому пересечению времени — цепочкой, как обычное
// объединение интервалов. Внутри кластера .col уже 0-based (колонки
// освобождаются между кластерами) и идёт подряд без дырок — на этом
// строится и локальная ширина кластера, и раскладка по рядам ниже.
function clusterOverlaps(items) {
  const sorted = [...items].sort((a, b) => a.startMin - b.startMin)
  const clusters = []
  let current = []
  let currentMaxEnd = -Infinity
  for (const item of sorted) {
    if (current.length === 0 || item.startMin < currentMaxEnd) {
      current.push(item)
      currentMaxEnd = Math.max(currentMaxEnd, item.endMin)
    } else {
      clusters.push(current)
      current = [item]
      currentMaxEnd = item.endMin
    }
  }
  if (current.length) clusters.push(current)
  return clusters
}

// Единая шкала времени для ВСЕЙ сетки (все дни/залы сразу — иначе часовые
// линии разъедутся между колонками). Обычно час = ROW_HEIGHT px. Но если в
// каком-то дне/зале нашёлся кластер больше чем из 2 одновременных занятий
// (реальный конфликт по залу/преподавателю, TRU-46), то ровно на диапазон
// этого пересечения высота растёт в нужное число раз — под лишние занятия,
// разложенные по 2 в ряд. Столбцы дней/залов при этом остаются фиксированной
// ширины, никогда не сжимаются и не скроллятся; растягивается только сама
// сетка по вертикали (у неё и так уже есть overflowY: auto на весь календарь).
function buildTimeScale(gridStartHour, hours, columns, itemsByColumn) {
  const baseMin = gridStartHour * 60
  const endMin = (hours[hours.length - 1] + 1) * 60
  const pxPerMin = ROW_HEIGHT / 60

  const expansions = []
  columns.forEach(col => {
    const { active } = itemsByColumn[col.id] || { active: [] }
    clusterOverlaps(active).forEach(cluster => {
      const localMaxCols = cluster.reduce((max, l) => Math.max(max, l.col + 1), 1)
      if (localMaxCols > 2) {
        expansions.push({
          startMin: Math.min(...cluster.map(l => l.startMin)),
          endMin: Math.max(...cluster.map(l => l.endMin)),
          numRows: Math.ceil(localMaxCols / 2),
        })
      }
    })
  })

  const boundarySet = new Set([baseMin, endMin])
  expansions.forEach(e => { boundarySet.add(e.startMin); boundarySet.add(e.endMin) })
  const boundaries = [...boundarySet].filter(m => m >= baseMin && m <= endMin).sort((a, b) => a - b)

  const cumulative = [0]
  for (let i = 0; i < boundaries.length - 1; i++) {
    const segStart = boundaries[i]
    const segEnd = boundaries[i + 1]
    const multiplier = expansions.reduce(
      (max, e) => (e.startMin <= segStart && e.endMin >= segEnd ? Math.max(max, e.numRows) : max),
      1
    )
    cumulative.push(cumulative[i] + (segEnd - segStart) * pxPerMin * multiplier)
  }

  function top(min) {
    const clamped = Math.min(Math.max(min, baseMin), endMin)
    let i = 0
    while (i < boundaries.length - 2 && boundaries[i + 1] < clamped) i++
    const segStart = boundaries[i]
    const segEnd = boundaries[i + 1] ?? segStart
    const segPx = cumulative[i + 1] - cumulative[i]
    const multiplier = segEnd > segStart ? segPx / ((segEnd - segStart) * pxPerMin) : 1
    return cumulative[i] + (clamped - segStart) * pxPerMin * multiplier
  }

  return { top, totalHeight: cumulative[cumulative.length - 1] }
}

// Отменённые/перенесённые занятия фактически освободили своё время (тот же
// принцип, что и в бэкенд-детекте конфликтов, TRU-46) — не должны отжимать
// место у нового занятия в сетке. Раскладываем их отдельно, узкой меткой
// сбоку, а не полноценной колонкой.
function splitActiveAndHistory(lessons) {
  const active = []
  const history = []
  lessons.forEach(l => {
    if (l.status === 'cancelled' || l.status === 'rescheduled') history.push(l)
    else active.push(l)
  })
  // layoutColumn и для history — не для ширины (метки не сжимаются), а
  // чтобы получить .col по реальному пересечению времени: иначе третья
  // отменённая запись дня сдвигалась бы наравне с первыми двумя, даже
  // если она в другое время и ни с чем не пересекается.
  return { active: layoutColumn(active), history: layoutColumn(history) }
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
  return t('Индив. занятие')
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
  const focusedLessonId = searchParams.get('lesson')

  const [view, setView] = useState(() => searchParams.get('view') || stored.view || 'week')
  const [date, setDate] = useState(() => searchParams.get('date') || toISODate(new Date()))
  const [filters, setFilters] = useState(() => ({
    branch: searchParams.get('branch') || (!focusedLessonId && stored.branch) || '',
    room: searchParams.get('room') || (!focusedLessonId && stored.room) || '',
    teacher: searchParams.get('teacher') || (!focusedLessonId && stored.teacher) || '',
    direction: searchParams.get('direction') || (!focusedLessonId && stored.direction) || '',
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
  const [whoToCallLessonId, setWhoToCallLessonId] = useState(null)
  const [createSlot, setCreateSlot] = useState(null)
  const [mobileDay, setMobileDay] = useState(() => {
    const weekday = new Date(date).getDay()
    return weekday === 0 ? 6 : weekday - 1
  })
  const [conflictsCount, setConflictsCount] = useState(0)
  const [showConflicts, setShowConflicts] = useState(false)
  const [showBulkCancel, setShowBulkCancel] = useState(false)
  const requestedLessonRef = useRef(focusedLessonId)
  const isMobile = useIsMobile()
  const navigate = useNavigate()
  const isTeacher = me?.role === 'teacher'
  const isOwnerOrManager = me?.role === 'owner' || me?.role === 'manager'

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

  useEffect(() => {
    const lessonId = requestedLessonRef.current
    if (!lessonId || loading) return
    const lesson = lessons.find(item => item.id === lessonId)
    if (lesson) setSelectedLesson(lesson)
    requestedLessonRef.current = null
  }, [lessons, loading])

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
    const raw = {}
    weekDays.forEach(d => { raw[toISODate(d)] = [] })
    lessons.forEach(lesson => {
      const dateStr = localDatePart(lesson.starts_at_local)
      if (!(dateStr in raw)) return
      raw[dateStr].push(withMinutes(lesson))
    })
    const map = {}
    Object.keys(raw).forEach(k => { map[k] = splitActiveAndHistory(raw[k]) })
    return map
  }, [lessons, weekDays])

  const byRoom = useMemo(() => {
    const raw = {}
    lessons.forEach(lesson => {
      const key = lesson.room || '__none__'
      if (!raw[key]) raw[key] = []
      raw[key].push(withMinutes(lesson))
    })
    const map = {}
    Object.keys(raw).forEach(k => { map[k] = splitActiveAndHistory(raw[k]) })
    return map
  }, [lessons])

  const dayColumns = useMemo(() => {
    const cols = filteredRooms.map(r => ({ id: r.id, name: r.name }))
    const none = byRoom.__none__
    if (none && (none.active.length + none.history.length) > 0) cols.push({ id: '__none__', name: t('Без зала') })
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

  function openCreateLesson() {
    const selectedDate = view === 'week' && isMobile ? toISODate(weekDays[mobileDay]) : date
    setCreateSlot({
      date: selectedDate,
      time: '09:00',
      room: filters.room || '',
      groupId: '',
      teacherId: filters.teacher || '',
      durationMin: 60,
    })
  }

  function closeSelectedLesson() {
    setSelectedLesson(null)
    if (searchParams.has('lesson')) {
      const next = new URLSearchParams(searchParams)
      next.delete('lesson')
      setSearchParams(next, { replace: true })
    }
  }

  function handleActionDone() { closeSelectedLesson(); setCreateSlot(null); load(); loadConflicts() }

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
        showBulkCancelBtn={isOwnerOrManager}
        onBulkCancel={() => setShowBulkCancel(true)}
        showMobileCreateBtn={isMobile && !isTeacher}
        onCreateLesson={openCreateLesson}
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
          lessons={lessons}
          onClose={closeSelectedLesson}
          onDone={handleActionDone}
          onAttendance={id => navigate(`/attendance?lesson=${id}&date=${localDatePart(selectedLesson.starts_at_local)}`)}
          onWhoToCall={id => { closeSelectedLesson(); setWhoToCallLessonId(id) }}
          onSelectReplacement={l => setSelectedLesson(l)}
          onCreateHere={l => {
            setSelectedLesson(null)
            const durationMin = Math.round((new Date(l.ends_at) - new Date(l.starts_at)) / 60000)
            setCreateSlot({
              date: localDatePart(l.starts_at_local),
              time: localTimePart(l.starts_at_local),
              room: l.room || '',
              groupId: l.group || '',
              teacherId: l.teacher || '',
              durationMin,
            })
          }}
        />
      )}

      {whoToCallLessonId && (
        <WhoToCallModal
          lessonId={whoToCallLessonId}
          onClose={() => setWhoToCallLessonId(null)}
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

      {showBulkCancel && (
        <BulkCancelModal
          filters={filters}
          onClose={() => setShowBulkCancel(false)}
          onDone={() => { setShowBulkCancel(false); load(); loadConflicts() }}
        />
      )}
    </div>
  )
}

function CalendarHeader({ label, view, onViewChange, onPrev, onNext, onToday, loading, conflictsCount, onShowConflicts, showBulkCancelBtn, onBulkCancel, showMobileCreateBtn, onCreateLesson }) {
  return (
    <div style={{
      background: '#fff', borderRadius: 16, padding: '16px 24px', marginBottom: 16,
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
      border: '1px solid #F0F0F5',
    }}>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>{t('Расписание')}</h1>
        <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{label}{loading ? ` · ${t('Загрузка…')}` : ''}</p>
      </div>
      <div className="kc-schedule-header-controls" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {conflictsCount > 0 && (
          <button
            onClick={onShowConflicts}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '0 14px', height: 36,
              border: '1.5px solid #FDE68A', borderRadius: 10, background: '#FFFBEB', color: '#B45309',
              fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
            }}
          >
            <AlertTriangle size={14} /> {t('Конфликты')} ({conflictsCount})
          </button>
        )}
        {showBulkCancelBtn && (
          <button
            onClick={onBulkCancel}
            title={t('Массовая отмена занятий за период')}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '0 14px', height: 36,
              border: '1px solid #F0F0F5', borderRadius: 10, background: '#fff', color: '#9CA3AF',
              fontSize: 13, fontWeight: 500, cursor: 'pointer', fontFamily: 'Manrope',
            }}
          >
            <Ban size={13} /> {t('Отменить за период')}
          </button>
        )}
        {showMobileCreateBtn && (
          <button
            className="kc-schedule-mobile-create"
            onClick={onCreateLesson}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
              minHeight: 40, padding: '0 16px', border: 'none', borderRadius: 10,
              background: 'linear-gradient(135deg, #FF9D8A 0%, #E4586E 100%)', color: '#fff',
              fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: 'Manrope',
            }}
          >
            <Plus size={16} /> {t('Новое занятие')}
          </button>
        )}
        <div className="kc-schedule-main-controls" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div className="kc-schedule-view-toggle" style={{ display: 'flex', background: '#F8F9FF', borderRadius: 10, padding: 3, gap: 2 }}>
            <ViewToggleBtn active={view === 'week'} onClick={() => onViewChange('week')} icon={<Rows3 size={14} />} label={t('Неделя')} />
            <ViewToggleBtn active={view === 'day'} onClick={() => onViewChange('day')} icon={<CalendarDays size={14} />} label={t('День')} />
          </div>
          <div className="kc-schedule-date-nav" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <button onClick={onPrev} style={navBtnStyle} aria-label={t('Назад')}><ChevronLeft size={16} /></button>
            <button className="kc-schedule-today" onClick={onToday} style={{ ...navBtnStyle, width: 'auto', padding: '0 16px', fontWeight: 600, fontSize: 13, color: ACCENT }}>{t('Сегодня')}</button>
            <button onClick={onNext} style={navBtnStyle} aria-label={t('Вперёд')}><ChevronRight size={16} /></button>
          </div>
        </div>
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
function Dropdown({
  value, onChange, options, width = 160, variant = 'filter', placeholder,
  searchable = false, searchPlaceholder,
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const ref = useRef()
  const inputRef = useRef()

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selected = options.find(([v]) => v === value)
  const active = variant === 'filter' && value !== ''
  const displayText = selected ? selected[1] : (placeholder ?? options[0][1])
  const normalizedQuery = query.trim().toLocaleLowerCase()
  const visibleOptions = searchable && normalizedQuery
    ? options.filter(([optionValue, label]) => {
        if (optionValue === '') return false
        const normalizedLabel = String(label).toLocaleLowerCase()
        return normalizedLabel.startsWith(normalizedQuery)
          || normalizedLabel.split(/\s+/).some(word => word.startsWith(normalizedQuery))
      })
    : options

  function close() {
    setOpen(false)
    setQuery('')
  }

  return (
    <div ref={ref} className={variant === 'filter' ? 'kc-schedule-filter' : undefined} style={{ width, flexShrink: 0, position: 'relative' }}>
      {searchable ? (
        <div
          style={{
            width: '100%', boxSizing: 'border-box', position: 'relative',
            border: `1.5px solid ${open ? ACCENT : '#EBEBF0'}`,
            borderRadius: 8, background: 'transparent',
            boxShadow: open ? `0 0 0 3px ${ACCENT}1F` : 'none',
            transition: 'border-color 0.15s, box-shadow 0.15s',
          }}
        >
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded={open}
            autoComplete="off"
            value={open ? query : (selected && selected[0] !== '' ? selected[1] : '')}
            placeholder={placeholder ?? searchPlaceholder ?? t('Начните вводить...')}
            onFocus={() => {
              setQuery('')
              setOpen(true)
            }}
            onChange={event => {
              setQuery(event.target.value)
              setOpen(true)
            }}
            onKeyDown={event => {
              if (event.key === 'Escape') {
                event.preventDefault()
                close()
                inputRef.current?.blur()
              }
              if (event.key === 'Enter' && visibleOptions.length > 0) {
                event.preventDefault()
                const firstChoice = visibleOptions.find(([optionValue]) => optionValue !== '') ?? visibleOptions[0]
                onChange(firstChoice[0])
                close()
              }
            }}
            style={{
              width: '100%', height: 38, boxSizing: 'border-box',
              border: 'none', outline: 'none', borderRadius: 8,
              background: 'transparent', padding: '9px 34px 9px 12px',
              fontSize: 13, fontFamily: 'Manrope', color: '#1A1A2E',
            }}
          />
          <button
            type="button"
            aria-label={t('Открыть список')}
            onMouseDown={event => event.preventDefault()}
            onClick={() => {
              if (open) close()
              else {
                setQuery('')
                setOpen(true)
                inputRef.current?.focus()
              }
            }}
            style={{
              position: 'absolute', top: 0, right: 0, width: 34, height: 38,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: 'none', background: 'transparent', color: '#9CA3AF', cursor: 'pointer',
            }}
          >
            <ChevronDown
              size={13}
              style={{ transform: open ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
            />
          </button>
        </div>
      ) : (
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
      )}

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
          {visibleOptions.length === 0 && (
            <div style={{ padding: '10px 12px', color: '#9CA3AF', fontSize: 12, fontFamily: 'Manrope' }}>
              {t('Ничего не найдено')}
            </div>
          )}
          {visibleOptions.map(([v, l]) => {
            const isSelected = value === v
            return (
              <div
                key={v}
                onClick={() => { onChange(v); close() }}
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
        options={[['', t('Все филиалы')], ...branches.map(b => [String(b.id), b.name])]}
      />
      <Dropdown
        value={filters.room}
        onChange={v => onChange({ room: v })}
        options={[['', t('Все залы')], ...rooms.map(r => [String(r.id), r.name])]}
      />
      <Dropdown
        value={filters.direction}
        onChange={v => onChange({ direction: v })}
        options={[['', t('Все направления')], ...directions.map(d => [String(d.id), d.name])]}
      />
      {isTeacher ? (
        <span style={{ fontSize: 12, color: ACCENT, fontWeight: 600, background: '#FDF0EE', padding: '8px 12px', borderRadius: 8 }}>
          {t('Показано ваше расписание')}
        </span>
      ) : (
        <Dropdown
          value={filters.teacher}
          onChange={v => onChange({ teacher: v })}
          options={[['', t('Все преподаватели')], ...teachers.map(teacher => [String(teacher.id), teacher.full_name])]}
          width={180}
        />
      )}
      {hasActive && (
        <button
          onClick={onReset}
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '8px 12px', border: 'none', background: 'none', color: '#9CA3AF', fontSize: 12, fontFamily: 'Manrope', cursor: 'pointer' }}
        >
          <X size={12} /> {t('Сбросить')}
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
  const totalCount = lesson.total_participants_count ?? lesson.enrolled_count

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
      title={hasConflict ? t('Пересекается по залу или преподавателю с другим занятием') : undefined}
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
            {lesson.capacity != null && ` · ${totalCount}/${lesson.capacity}`}
          </div>
          {!dimmed && lesson.trial_count > 0 && (
            <div style={{ fontSize: 9, fontWeight: 700, color: '#7C3AED', whiteSpace: 'nowrap' }}>
              {t('Пробное: {count}', { count: lesson.trial_count })}
            </div>
          )}
          {dimmed && (
            <div style={{ fontSize: 9, fontWeight: 700, color: isCancelled ? '#DC2626' : '#D97706', marginTop: 2 }}>
              {isCancelled ? t('ОТМЕНЕНО') : t('ПЕРЕНЕСЕНО')}
            </div>
          )}
          {hasConflict && (
            <div style={{ fontSize: 9, fontWeight: 700, color: '#B45309', marginTop: 2 }}>{t('КОНФЛИКТ')}</div>
          )}
    </div>
  )
}

const HISTORY_MARKER_WIDTH = 8
const HISTORY_BASE_OFFSET = 0

// Одна метка на группу отменённых/перенесённых занятий, пересекающихся по
// времени (см. splitActiveAndHistory) — не занимает колонку, время
// фактически свободно, на нём уже может стоять новое занятие в полную
// ширину. Раньше рисовалась отдельная полоска на КАЖДОЕ такое занятие —
// при нескольких переносах подряд получался "частокол" из полосок; теперь
// это одна метка (с счётчиком, если записей больше одной). Если занятие
// одно — клик сразу открывает его карточку. Если несколько — список
// открывается КЛИКОМ (не наведением: при наведении список пропадал, как
// только мышь уходила с узкой полоски по пути к нему) и остаётся открытым,
// пока не выбрали занятие или не кликнули снаружи.
function HistoryMarker({ items, onSelect, style }) {
  const [open, setOpen] = useState(false)
  const [hover, setHover] = useState(false)
  const ref = useRef()
  const hasRescheduled = items.some(l => l.status === 'rescheduled')
  const baseColor = hasRescheduled ? '240, 180, 41' : '156, 163, 175'
  const color = `rgba(${baseColor}, ${hover || open ? 0.85 : 0.55})`

  useEffect(() => {
    if (!open) return
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div
      ref={ref}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={e => {
        e.stopPropagation()
        if (items.length === 1) onSelect(items[0])
        else setOpen(o => !o)
      }}
      style={{
        position: 'absolute', right: HISTORY_BASE_OFFSET, width: 16,
        display: 'flex', justifyContent: 'flex-end', cursor: 'pointer', zIndex: open ? 20 : 2,
        ...style,
      }}
    >
      <div style={{
        width: HISTORY_MARKER_WIDTH, height: '100%', borderRadius: 3, background: color,
        transition: 'background 0.15s',
      }} />
      {items.length > 1 && (
        <div style={{
          position: 'absolute', top: 2, right: 1, minWidth: 14, height: 14, padding: '0 3px',
          borderRadius: 8, background: '#1A1A2E', color: '#fff', fontSize: 9, fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1,
        }}>
          {items.length}
        </div>
      )}
      {open && (
        <div style={{
          position: 'absolute', top: 0, right: '100%', marginRight: 6,
          background: '#1A1A2E', color: '#fff', borderRadius: 8, padding: 6,
          fontSize: 11, fontFamily: 'Manrope', whiteSpace: 'nowrap',
          boxShadow: '0 6px 16px rgba(0,0,0,0.25)', maxHeight: 220, overflowY: 'auto',
        }}>
          {items.map((lesson, i) => {
            const isCancelled = lesson.status === 'cancelled'
            return (
              <div
                key={lesson.id}
                onClick={e => { e.stopPropagation(); setOpen(false); onSelect(lesson) }}
                style={{
                  padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
                  borderTop: i > 0 ? '1px solid rgba(255,255,255,0.1)' : 'none',
                }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(255,255,255,0.08)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
              >
                <div style={{ fontWeight: 700, color: isCancelled ? '#F87171' : '#FBBF24', marginBottom: 2 }}>
                  {isCancelled ? t('ОТМЕНЕНО') : t('ПЕРЕНЕСЕНО')}
                </div>
                <div style={{ fontWeight: 600 }}>{lessonTitle(lesson)}</div>
                <div style={{ color: '#9CA3AF', marginTop: 2 }}>
                  {localTimePart(lesson.starts_at_local)}–{localTimePart(lesson.ends_at_local)}
                  {lesson.room_name && ` · ${lesson.room_name}`}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// Общая временная сетка (колонки + часы слева) — переиспользуется недельным
// видом (колонки = дни) и дневным видом (колонки = залы).
function TimeGrid({ columns, columnHeader, itemsByColumn, hours, loading, emptyText, onSelectLesson, onSelectSlot }) {
  const gridStartHour = hours[0] ?? 8
  const templateColumns = `56px repeat(${columns.length || 1}, 1fr)`

  const { top: dynTop, totalHeight } = useMemo(
    () => buildTimeScale(gridStartHour, hours, columns, itemsByColumn),
    [gridStartHour, hours, columns, itemsByColumn]
  )

  const isEmpty = !loading && columns.every(c => !(itemsByColumn[c.id]?.active.length))

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', overflow: 'hidden' }}>
      <div style={{ maxHeight: '70vh', overflowY: 'auto' }}>
        <div style={{ display: 'grid', gridTemplateColumns: templateColumns, borderBottom: '1px solid #F0F0F5', position: 'sticky', top: 0, zIndex: 30, background: '#fff' }}>
          <div />
          {columns.map(col => (
            <div key={col.id} style={{ padding: '10px 8px', textAlign: 'center', borderLeft: '1px solid #F0F0F5', background: col.highlighted ? '#FDF0EE' : '#fff' }}>
              {columnHeader(col)}
            </div>
          ))}
        </div>

        {columns.length === 0 ? (
          <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
            {t('Нет залов, подходящих под фильтр.')}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: templateColumns, position: 'relative' }}>
            <div style={{ position: 'relative', height: totalHeight }}>
              {hours.map(h => (
                <div key={h} style={{ position: 'absolute', top: dynTop(h * 60), left: 0, right: 0, textAlign: 'right', paddingRight: 8, paddingTop: 4, boxSizing: 'border-box', fontSize: 11, color: '#9CA3AF' }}>
                  {String(h).padStart(2, '0')}:00
                </div>
              ))}
            </div>
            {columns.map(col => {
            const { active, history } = itemsByColumn[col.id] || { active: [], history: [] }
            // Столбцы (дни/залы) — ФИКСИРОВАННОЙ ширины, никогда не сжимаются
            // и не скроллятся. Занятия группируются в кластеры по факту
            // пересечения времени; ширина внутри кластера считается только
            // от него самого (не от всех занятий дня/зала) — иначе конфликт
            // в одной ячейке делал бы уже занятия в других, не связанных с
            // ним. Если пересеклось больше двух (реальный конфликт по залу/
            // преподавателю, TRU-46) — лишние уходят по 2 в новый ряд ниже, а
            // сама сетка растёт по высоте ровно на диапазон этого пересечения
            // (buildTimeScale), не наезжая на чужое время и не трогая ширину.
            const clusters = clusterOverlaps(active)
            return (
              <div key={col.id} style={{ position: 'relative', borderLeft: '1px solid #F0F0F5', height: totalHeight, overflow: 'hidden' }}>
                {hours.map(h => (
                  <div
                    key={h}
                    onClick={() => onSelectSlot?.({ col, time: `${String(h).padStart(2, '0')}:00` })}
                    style={{ position: 'absolute', top: dynTop(h * 60), left: 0, right: 0, height: dynTop((h + 1) * 60) - dynTop(h * 60), borderBottom: '1px solid #F7F7FA', cursor: onSelectSlot ? 'pointer' : 'default' }}
                    onMouseEnter={e => { if (onSelectSlot) e.currentTarget.style.background = '#FAFAFA' }}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  />
                ))}
                {clusters.map(cluster => {
                  const localMaxCols = cluster.reduce((max, l) => Math.max(max, l.col + 1), 1)
                  if (localMaxCols <= 2) {
                    // Обычный случай — без пересечений (или максимум два
                    // рядом) чипы делят ширину ячейки пополам, как раньше.
                    // Высота — по факту длительности занятия (не через
                    // dynTop), иначе одиночные занятия в других днях/залах
                    // растягивались бы под масштаб чужой расширенной ячейки —
                    // выше сдвигается только позиция (top), а не высота.
                    return cluster.map(lesson => (
                      <LessonChip
                        key={lesson.id}
                        lesson={lesson}
                        onClick={e => { e.stopPropagation(); onSelectLesson(lesson) }}
                        style={{
                          top: dynTop(lesson.startMin) + 1,
                          height: Math.max((lesson.endMin - lesson.startMin) * ROW_HEIGHT / 60 - 2, 22),
                          left: `calc(${(lesson.col / localMaxCols) * 100}% + 2px)`,
                          width: `calc(${(1 / localMaxCols) * 100}% - 4px)`,
                          zIndex: 1,
                        }}
                      />
                    ))
                  }
                  // Реальный конфликт (3+ занятий разом) — по 2 в ряд, лишние
                  // уходят новым рядом вниз, внутри собственной, уже
                  // зарезервированной под них высоты (без скролла и без
                  // изменения ширины столбца).
                  const numRows = Math.ceil(localMaxCols / 2)
                  const clusterStartMin = Math.min(...cluster.map(l => l.startMin))
                  const clusterEndMin = Math.max(...cluster.map(l => l.endMin))
                  const clusterTop = dynTop(clusterStartMin)
                  const rowHeight = (dynTop(clusterEndMin) - clusterTop) / numRows
                  return cluster.map(lesson => {
                    const row = Math.floor(lesson.col / 2)
                    const lane = lesson.col % 2
                    const lanesInRow = row === numRows - 1 && localMaxCols % 2 === 1 ? 1 : 2
                    return (
                      <LessonChip
                        key={lesson.id}
                        lesson={lesson}
                        onClick={e => { e.stopPropagation(); onSelectLesson(lesson) }}
                        style={{
                          top: clusterTop + row * rowHeight + 1,
                          height: Math.max(rowHeight - 2, 22),
                          left: `calc(${(lane / lanesInRow) * 100}% + 2px)`,
                          width: `calc(${(1 / lanesInRow) * 100}% - 4px)`,
                          zIndex: 1,
                        }}
                      />
                    )
                  })
                })}
                {clusterOverlaps(history).map((group, gi) => {
                  const groupStartMin = Math.min(...group.map(l => l.startMin))
                  const groupEndMin = Math.max(...group.map(l => l.endMin))
                  return (
                    <HistoryMarker
                      key={`history-${gi}`}
                      items={group}
                      onSelect={onSelectLesson}
                      style={{
                        top: dynTop(groupStartMin) + 1,
                        height: Math.max((groupEndMin - groupStartMin) * ROW_HEIGHT / 60 - 2, 14),
                      }}
                    />
                  )
                })}
              </div>
            )
            })}
          </div>
        )}
      </div>

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
            {t(WEEKDAY_LABELS[col.day.getDay() === 0 ? 6 : col.day.getDay() - 1])}
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: col.highlighted ? ACCENT : '#1A1A2E' }}>{col.day.getDate()}</div>
        </>
      )}
      itemsByColumn={byDay}
      hours={hours}
      loading={loading}
      emptyText={t('На этой неделе занятий нет. Кликните по пустому слоту, чтобы создать.')}
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
      emptyText={t('На этот день занятий нет. Кликните по пустому слоту, чтобы создать.')}
      onSelectLesson={onSelectLesson}
      onSelectSlot={onSelectSlot ? (slot => onSelectSlot({
        date,
        time: slot.time,
        room: slot.col.id === '__none__' ? '' : slot.col.id,
      })) : undefined}
    />
  )
}

// Мобильные списки — уже вертикальный список, сжатия в колонку не
// происходит, так что active/history можно просто слить обратно вместе.
function flattenColumn(entry) {
  return entry ? [...entry.active, ...entry.history] : []
}

function MobileWeekDayView({ weekDays, mobileDay, setMobileDay, byDay, loading, onSelectLesson }) {
  const day = weekDays[mobileDay]
  const dateStr = toISODate(day)
  const dayLessons = flattenColumn(byDay[dateStr]).sort((a, b) => a.startMin - b.startMin)

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
                {t(WEEKDAY_LABELS[i])}
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: active ? ACCENT : '#1A1A2E' }}>{d.getDate()}</div>
            </button>
          )
        })}
      </div>

      <div style={{ padding: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', marginBottom: 10 }}>{formatDayLabel(day)}</div>
        <LessonList lessons={dayLessons} loading={loading} emptyText={t('Занятий нет')} onSelectLesson={onSelectLesson} showRoom />
      </div>
    </div>
  )
}

function MobileDayRoomsView({ date, columns, byRoom, loading, onSelectLesson }) {
  const nonEmptyColumns = columns.filter(c => flattenColumn(byRoom[c.id]).length > 0)

  return (
    <div style={{ background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', padding: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', marginBottom: 10 }}>{formatDayLabel(new Date(date))}</div>
      {loading ? (
        <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{t('Загрузка…')}</div>
      ) : nonEmptyColumns.length === 0 ? (
        <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{t('На этот день занятий нет')}</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {nonEmptyColumns.map(col => (
            <div key={col.id}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', marginBottom: 8 }}>{col.name}</div>
              <LessonList
                lessons={flattenColumn(byRoom[col.id]).sort((a, b) => a.startMin - b.startMin)}
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
  if (loading) return <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{t('Загрузка…')}</div>
  if (lessons.length === 0) return emptyText ? <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{emptyText}</div> : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {lessons.map(lesson => {
        const color = lesson.direction_color || DEFAULT_COLOR
        const dimmed = lesson.status === 'cancelled' || lesson.status === 'rescheduled'
        const hasConflict = lesson.has_conflict && !dimmed
        const isIndividual = lesson.is_individual && !dimmed && !hasConflict
        const totalCount = lesson.total_participants_count ?? lesson.enrolled_count
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
                {lesson.capacity != null && ` · ${totalCount}/${lesson.capacity}`}
              </div>
              {!dimmed && lesson.trial_count > 0 && (
                <div style={{ fontSize: 10, fontWeight: 700, color: '#7C3AED', marginTop: 3 }}>
                  {t('Пробное: {count}', { count: lesson.trial_count })}
                </div>
              )}
              {dimmed && (
                <div style={{ fontSize: 10, fontWeight: 700, color: lesson.status === 'cancelled' ? '#DC2626' : '#D97706', marginTop: 4 }}>
                  {t(STATUS_LABEL[lesson.status])}
                </div>
              )}
              {hasConflict && (
                <div style={{ fontSize: 10, fontWeight: 700, color: '#B45309', marginTop: 4 }}>{t('КОНФЛИКТ ПО ЗАЛУ/ПРЕПОДАВАТЕЛЮ')}</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function BulkCancelModal({ filters, onClose, onDone }) {
  const today = toISODate(new Date())
  const [dateFrom, setDateFrom] = useState(today)
  const [dateTo, setDateTo] = useState(today)
  const [reasonCategory, setReasonCategory] = useState('')
  const [comment, setComment] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!reasonCategory) { setError(t('Выберите причину отмены')); return }
    if (reasonCategory === 'other' && !comment.trim()) { setError(t('Для причины «Другое» нужен комментарий')); return }
    setSaving(true); setError('')
    try {
      const res = await bulkCancelLessons({ dateFrom, dateTo, reasonCategory, comment, filters })
      setResult(res)
    } catch (e2) {
      setError(e2.response?.data?.reason_category?.[0] || e2.response?.data?.comment?.[0] || e2.response?.data?.detail || t('Не удалось отменить занятия'))
    } finally { setSaving(false) }
  }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <Ban size={16} style={{ color: '#DC2626' }} /> {t('Массовая отмена')}
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        {result ? (
          <div>
            <div style={{ background: '#F0FDF4', border: '1.5px solid #BBF7D0', borderRadius: 10, padding: '14px 16px', marginBottom: 16, fontSize: 13, color: '#166534', fontFamily: 'Manrope' }}>
              {t('Отменено занятий: {count}', { count: result.cancelled_count })}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button style={primaryBtn} onClick={onDone}>{t('Готово')}</button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <p style={{ fontSize: 12, color: '#9CA3AF', margin: '0 0 14px', lineHeight: 1.6 }}>
              {t('Отменит все запланированные занятия за период — например, на каникулы или праздники. Уже отменённые, проведённые или перенесённые занятия не тронет.')}
            </p>
            <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>{t('Дата с')} *</label>
                <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} required style={inputStyle} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>{t('Дата по')} *</label>
                <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} required style={inputStyle} />
              </div>
            </div>
            <div style={{ marginBottom: 14 }}>
              <label style={labelStyle}>{t('Причина отмены')} *</label>
              <Dropdown
                variant="field"
                width="100%"
                value={reasonCategory}
                onChange={setReasonCategory}
                placeholder={t('Выберите причину')}
                options={[['', t('Выберите причину')], ...CANCEL_REASON_OPTIONS.map(([value, label]) => [value, t(label)])]}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={labelStyle}>{t('Комментарий')}{reasonCategory === 'other' ? ' *' : ''}</label>
              <textarea value={comment} onChange={e => setComment(e.target.value)} rows={3} maxLength={2000} style={{ ...inputStyle, resize: 'vertical' }} placeholder={reasonCategory === 'other' ? t('Обязательно для причины «Другое»') : t('Необязательно')} />
            </div>
            {(filters.branch || filters.room || filters.teacher || filters.direction) && (
              <p style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 14 }}>
                {t('Учитываются текущие фильтры календаря (филиал/зал/преподаватель/направление).')}
              </p>
            )}
            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{error}</p>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" style={secondaryBtn} onClick={onClose}>{t('Отмена')}</button>
              <button type="submit" disabled={saving} style={{ padding: '10px 18px', border: 'none', borderRadius: 8, background: '#DC2626', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
                {saving ? t('Отмена…') : t('Отменить занятия')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

function WhoToCallModal({ lessonId, onClose }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(null)

  const load = useCallback(() => {
    setLoading(true); setError('')
    fetchWhoToCall(lessonId)
      .then(setData)
      .catch(e => setError(e.response?.data?.detail || t('Не удалось загрузить список')))
      .finally(() => setLoading(false))
  }, [lessonId])

  useEffect(() => { load() }, [load])

  // Оптимистично меняем локальное состояние сразу — карточка отвечает без
  // рывка от перерисовки всего списка, запрос идёт в фоне; при ошибке
  // откатываем обратно.
  function contactKey(contact) {
    return contact.contact_key || `parent:${contact.parent_contact_id}`
  }

  function setContactCalled(key, called) {
    setData(prev => ({
      ...prev,
      contacts: prev.contacts.map(c => contactKey(c) === key ? { ...c, called } : c),
    }))
  }

  async function toggleCalled(contact) {
    const nextCalled = !contact.called
    const key = contactKey(contact)
    setPending(key)
    setContactCalled(key, nextCalled)
    try {
      if (nextCalled) await markCalled(lessonId, contact, 'call')
      else await unmarkCalled(lessonId, contact)
    } catch (e) {
      setContactCalled(key, contact.called) // откат
      setError(e.response?.data?.detail || t('Не удалось сохранить отметку'))
    } finally { setPending(null) }
  }

  function handleWhatsappClick(contact) {
    // Открытие чата — тоже сигнал, что связались; отмечаем как обзвонено,
    // если ещё не отмечено (не блокирует переход по ссылке).
    if (!contact.called) {
      const key = contactKey(contact)
      setContactCalled(key, true)
      markCalled(lessonId, contact, 'whatsapp').catch(() => setContactCalled(key, false))
    }
  }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div style={{ ...modalBox, maxWidth: 560, maxHeight: '85vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <PhoneCall size={16} style={{ color: ACCENT }} /> {t('Кого обзвонить')}
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{t('Загрузка…')}</div>
        ) : error ? (
          <p style={{ color: '#DC2626', fontSize: 13 }}>{error}</p>
        ) : (
          <>
            <div style={{ background: '#F8F9FF', border: '1px solid #F0F0F5', borderRadius: 10, padding: '10px 12px', margin: '10px 0 16px', fontSize: 12, color: '#6B7280', fontFamily: 'Manrope', lineHeight: 1.6 }}>
              {data.message}
            </div>
            {data.contacts.length === 0 ? (
              <p style={{ fontSize: 13, color: '#9CA3AF', textAlign: 'center', padding: 24 }}>{t('Контактов не найдено.')}</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {data.contacts.map(contact => (
                  <div key={contactKey(contact)} style={{
                    border: `1px solid ${contact.called ? '#BBF7D0' : '#F0F0F5'}`,
                    background: contact.called ? '#F0FDF4' : '#fff',
                    borderRadius: 10, padding: '12px 14px',
                    transition: 'background-color 0.25s ease, border-color 0.25s ease',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#1A1A2E', fontFamily: 'Manrope' }}>
                          {contact.parent_contact_name}
                          {contact.roles.length > 0 && <span style={{ fontWeight: 400, color: '#9CA3AF' }}> · {contact.roles.join(', ')}</span>}
                        </div>
                        <div style={{ fontSize: 11, color: '#9CA3AF', fontFamily: 'Manrope', marginTop: 2 }}>
                          {contact.children.map(c => c.full_name).join(', ')}
                          {contact.source_lead_id && (
                            <> · <Link to={`/leads/${contact.source_lead_id}`} style={{ color: '#7C3AED', fontWeight: 700 }}>{t('Открыть заявку')}</Link></>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={() => toggleCalled(contact)}
                        disabled={pending === contactKey(contact)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 4, padding: '5px 10px', borderRadius: 7,
                          border: `1px solid ${contact.called ? '#16A34A' : '#EBEBF0'}`,
                          background: contact.called ? '#16A34A' : '#fff',
                          color: contact.called ? '#fff' : '#6B7280',
                          fontSize: 11, fontWeight: 600, fontFamily: 'Manrope', cursor: 'pointer', whiteSpace: 'nowrap',
                          opacity: pending === contactKey(contact) ? 0.6 : 1,
                          transition: 'background-color 0.25s ease, border-color 0.25s ease, color 0.25s ease, opacity 0.15s ease',
                        }}
                      >
                        {contact.called ? <><Check size={12} /> {t('Обзвонен')}</> : t('Отметить обзвон')}
                      </button>
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {contact.phones.map(phone => (
                        <a key={phone} href={`tel:${phone}`} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 7, border: '1px solid #EBEBF0', color: '#374151', fontSize: 12, fontFamily: 'Manrope', textDecoration: 'none' }}>
                          <Phone size={12} /> {phone}
                        </a>
                      ))}
                      {contact.whatsapp_link && (
                        <a
                          href={contact.whatsapp_link}
                          target="_blank"
                          rel="noreferrer"
                          onClick={() => handleWhatsappClick(contact)}
                          style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', borderRadius: 7, border: '1px solid #BBF7D0', background: '#F0FDF4', color: '#16A34A', fontSize: 12, fontWeight: 600, fontFamily: 'Manrope', textDecoration: 'none' }}
                        >
                          <MessageCircle size={12} /> WhatsApp
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
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
            <AlertTriangle size={16} style={{ color: '#B45309' }} /> {t('Текущие конфликты')}
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>
        <p style={{ fontSize: 12, color: '#9CA3AF', margin: '0 0 16px' }}>
          {t('Занятия, которые пересекаются по залу или преподавателю — от сегодня и дальше.')}
        </p>

        {loading ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{t('Загрузка…')}</div>
        ) : conflicts.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>{t('Конфликтов нет')}</div>
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
                    {lesson.room_name || t('без зала')} · {lesson.teacher_name || t('без преподавателя')}
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
          {t('Пересекается с {lessons} по залу или преподавателю', { lessons: conflicts.length === 1 ? t('занятием') : t('занятиями') })}
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
        <button type="button" onClick={onBack} style={secondaryBtn}>{t('Изменить')}</button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={saving}
          style={{ padding: '10px 18px', border: 'none', borderRadius: 8, background: '#D97706', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}
        >
          {saving ? t('Сохранение…') : t('Всё равно сохранить')}
        </button>
      </div>
    </div>
  )
}

const modalOverlay = { position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }
const modalBox = { background: '#fff', borderRadius: 16, width: '100%', maxWidth: 420, maxHeight: 'calc(100vh - 32px)', overflowY: 'auto', overscrollBehavior: 'contain', padding: '24px 24px 20px', fontFamily: 'Manrope' }
const primaryBtn = { display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '10px 18px', border: 'none', borderRadius: 8, background: `linear-gradient(135deg, #E8998D, ${ACCENT})`, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }
const secondaryBtn = { padding: '10px 18px', border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }
const dangerBtn = { ...secondaryBtn, color: '#DC2626', borderColor: '#FECACA' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box' }
const labelStyle = { display: 'block', fontSize: 11, fontWeight: 600, color: '#9CA3AF', marginBottom: 5, textTransform: 'uppercase', letterSpacing: '0.06em' }

function LessonDetailsModal({ lesson, lessons, onClose, onDone, onAttendance, onWhoToCall, onCreateHere, onSelectReplacement }) {
  const [mode, setMode] = useState('view') // view | cancel | reschedule
  const [reasonCategory, setReasonCategory] = useState('')
  const [comment, setComment] = useState('')
  const [newDate, setNewDate] = useState(localDatePart(lesson.starts_at_local))
  const [newTime, setNewTime] = useState(localTimePart(lesson.starts_at_local))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [conflicts, setConflicts] = useState(null)

  const canAct = lesson.status === 'scheduled'
  // Отменённое/перенесённое занятие не проводилось — отмечать посещаемость
  // там нечего (перенесённое — это уже новое занятие в другом времени).
  const canMarkAttendance = lesson.status === 'scheduled' || lesson.status === 'completed'
  const durationMs = new Date(lesson.ends_at) - new Date(lesson.starts_at)

  // Если на месте отменённого/перенесённого занятия уже создано новое
  // (тот же зал, пересекающееся время, активный статус) — предлагать
  // создать ещё одно бессмысленно, лучше открыть уже существующее.
  const replacementExists = (lessons || []).find(l => (
    l.id !== lesson.id
    && (l.status === 'scheduled' || l.status === 'completed')
    && l.room && lesson.room && l.room === lesson.room
    && new Date(l.starts_at) < new Date(lesson.ends_at)
    && new Date(lesson.starts_at) < new Date(l.ends_at)
  )) || null

  async function handleCancel() {
    if (!reasonCategory) { setError(t('Выберите причину отмены')); return }
    if (reasonCategory === 'other' && !comment.trim()) { setError(t('Для причины «Другое» нужен комментарий')); return }
    setSaving(true); setError('')
    try {
      await cancelLesson(lesson.id, { reasonCategory, comment })
      onDone()
    } catch (e) { setError(e.response?.data?.reason_category?.[0] || e.response?.data?.comment?.[0] || e.response?.data?.detail || t('Не удалось отменить занятие')) }
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
        setError(e.response?.data?.detail || t('Не удалось перенести занятие'))
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
              {lesson.is_individual ? t('Индивидуальное занятие') : t('Групповое занятие')} · {t(STATUS_LABEL[lesson.status])}
            </p>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        {mode === 'view' && (
          <>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 20 }}>
              <InfoRow icon={<MapPin size={14} />} text={`${localTimePart(lesson.starts_at_local)}–${localTimePart(lesson.ends_at_local)} · ${lesson.room_name || t('зал не указан')}`} />
              <InfoRow icon={<UserIcon size={14} />} text={lesson.teacher_name || t('преподаватель не назначен')} />
              {lesson.trial_count > 0 && (
                <InfoRow
                  icon={<Users size={14} />}
                  text={t('Пробное: {count}', { count: lesson.trial_count })}
                />
              )}
              {lesson.is_individual && (
                <InfoRow icon={<Users size={14} />} text={lesson.individual_children_names?.length ? lesson.individual_children_names.join(', ') : t('дети не указаны')} />
              )}
              {lesson.additional_participants?.length > 0 && (
                <div style={{ border: '1px solid #E9E7EF', borderRadius: 10, padding: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#8B8798', marginBottom: 7, textTransform: 'uppercase' }}>
                    {t('Дополнительные участники')}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                    {lesson.additional_participants.map(participant => {
                      const kind = ENROLLMENT_KIND_UI[participant.kind]
                      return (
                        <div key={participant.enrollment_id} style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 7 }}>
                          <span style={{ flex: 1, minWidth: 120, fontSize: 12.5, fontWeight: 650, color: '#1A1A2E' }}>{participant.child_name}</span>
                          {kind && (
                            <span style={{ color: kind.color, background: kind.background, border: `1px solid ${kind.border}`, borderRadius: 999, padding: '2px 8px', fontSize: 10, fontWeight: 750 }}>
                              {t(kind.label)}
                            </span>
                          )}
                          {participant.kind === 'trial' && participant.source_lead_id && (
                            <Link to={`/leads/${participant.source_lead_id}`} style={{ color: '#7C3AED', fontSize: 11, fontWeight: 700, textDecoration: 'none' }}>
                              {t('Открыть заявку')}
                            </Link>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
              {lesson.status === 'cancelled' && lesson.cancel_reason_category_display && (
                <div style={{ fontSize: 12, color: '#DC2626', background: '#FEF2F2', borderRadius: 8, padding: '8px 10px' }}>
                  {t('Причина отмены:')} {t(lesson.cancel_reason_category_display)}
                  {lesson.cancel_reason && ` — ${lesson.cancel_reason}`}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {!canMarkAttendance && !canAct && (
                <p style={{ fontSize: 12, color: '#9CA3AF', textAlign: 'center', margin: '4px 0' }}>
                  {lesson.status === 'rescheduled' ? t('Занятие перенесено.') : t('Занятие отменено.')}
                </p>
              )}
              {(lesson.status === 'cancelled' || lesson.status === 'rescheduled') && (
                <button style={{ ...secondaryBtn, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }} onClick={() => onWhoToCall(lesson.id)}>
                  <PhoneCall size={13} /> {t('Кого обзвонить')}
                </button>
              )}
              {(lesson.status === 'cancelled' || lesson.status === 'rescheduled') && (
                replacementExists ? (
                  <button
                    style={{ ...secondaryBtn, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, cursor: 'pointer' }}
                    onClick={() => onSelectReplacement(replacementExists)}
                  >
                    <Check size={13} style={{ color: '#16A34A' }} /> {t('На этом месте уже есть занятие — открыть')}
                  </button>
                ) : (
                  <button style={{ ...secondaryBtn, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }} onClick={() => onCreateHere(lesson)}>
                    <Plus size={13} /> {t('Создать занятие на этом месте')}
                  </button>
                )
              )}
              {canMarkAttendance && (
                <button style={primaryBtn} onClick={() => onAttendance(lesson.id)}>{t('Отметить посещаемость')}</button>
              )}
              {canAct && (
                <>
                  <button style={secondaryBtn} onClick={() => setMode('reschedule')}>{t('Перенести')}</button>
                  <button style={dangerBtn} onClick={() => setMode('cancel')}>{t('Отменить занятие')}</button>
                </>
              )}
            </div>
          </>
        )}

        {mode === 'cancel' && (
          <div>
            <label style={labelStyle}>{t('Причина отмены')} *</label>
            <div style={{ marginBottom: 14 }}>
              <Dropdown
                variant="field"
                width="100%"
                value={reasonCategory}
                onChange={setReasonCategory}
                placeholder={t('Выберите причину')}
                options={[['', t('Выберите причину')], ...CANCEL_REASON_OPTIONS.map(([value, label]) => [value, t(label)])]}
              />
            </div>
            <label style={labelStyle}>{t('Комментарий')}{reasonCategory === 'other' ? ' *' : ''}</label>
            <textarea value={comment} onChange={e => setComment(e.target.value)} rows={3} style={{ ...inputStyle, marginBottom: 14, resize: 'vertical' }} placeholder={reasonCategory === 'other' ? t('Обязательно для причины «Другое»') : t('Необязательно')} />
            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 10 }}>{error}</p>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button style={secondaryBtn} onClick={() => setMode('view')}>{t('Назад')}</button>
              <button style={{ ...dangerBtn, background: '#DC2626', color: '#fff', borderColor: '#DC2626' }} disabled={saving} onClick={handleCancel}>
                {saving ? t('Отмена…') : t('Подтвердить отмену')}
              </button>
            </div>
          </div>
        )}

        {mode === 'reschedule' && (
          <div>
            <div style={{ display: 'flex', gap: 10, marginBottom: 14 }}>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>{t('Дата')}</label>
                <input type="date" value={newDate} onChange={e => setNewDate(e.target.value)} style={inputStyle} />
              </div>
              <div style={{ flex: 1 }}>
                <label style={labelStyle}>{t('Время')}</label>
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
                <button style={secondaryBtn} onClick={() => setMode('view')}>{t('Назад')}</button>
                <button style={primaryBtn} disabled={saving} onClick={handleReschedule}>
                  {saving ? t('Перенос…') : t('Перенести')}
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
          placeholder={t('Начните вводить имя...')}
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
                {c.full_name}{c.age != null && <span style={{ color: '#9CA3AF' }}> · {c.age} {t('лет')}</span>}
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
  const [groupId, setGroupId] = useState(slot.groupId || '')
  const [children, setChildren] = useState([]) // [{id, full_name}]
  const [roomId, setRoomId] = useState(slot.room || '')
  const [teacherId, setTeacherId] = useState(slot.teacherId || '')
  const [time, setTime] = useState(slot.time)
  const [durationMin, setDurationMin] = useState(slot.durationMin || 60)
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
        setError(e2.response?.data?.detail || t('Не удалось создать занятие'))
      }
    } finally { setSaving(false) }
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (lessonType === 'group' && !groupId) { setError(t('Выберите группу')); return }
    if (lessonType === 'individual' && children.length === 0) { setError(t('Выберите хотя бы одного ребёнка')); return }
    submit(buildPayload())
  }

  return (
    <div style={modalOverlay} onClick={onClose}>
      <div className="kc-schedule-create-modal" style={modalBox} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>{t('Новое занятие')}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="kc-schedule-lesson-type" style={{ display: 'flex', background: '#F8F9FF', borderRadius: 10, padding: 3, gap: 2, marginBottom: 14 }}>
            <ViewToggleBtn active={lessonType === 'group'} onClick={() => setLessonType('group')} icon={<Users size={14} />} label={t('Групповое')} />
            <ViewToggleBtn active={lessonType === 'individual'} onClick={() => setLessonType('individual')} icon={<UserIcon size={14} />} label={t('Индивидуальное')} />
          </div>

          {lessonType === 'group' ? (
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>{t('Группа')} *</label>
              <Dropdown
                variant="field"
                width="100%"
                value={groupId}
                onChange={setGroupId}
                placeholder={t('Выберите группу')}
                searchable
                searchPlaceholder={t('Введите название группы')}
                options={[['', t('Выберите группу')], ...groups.map(g => [String(g.id), g.name])]}
              />
            </div>
          ) : (
            <div style={{ marginBottom: 12 }}>
              <label style={labelStyle}>{t('Ребёнок (или несколько)')} *</label>
              <ChildrenMultiSelect value={children} onChange={setChildren} />
            </div>
          )}
          <div className="kc-schedule-form-row" style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <label style={labelStyle}>{t('Дата')}</label>
              <input type="date" value={slot.date} disabled style={{ ...inputStyle, background: '#FAFAFA', color: '#9CA3AF' }} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <label style={labelStyle}>{t('Время')}</label>
              <input type="time" value={time} onChange={e => setTime(e.target.value)} style={inputStyle} required />
            </div>
            <div style={{ width: 90 }}>
              <label style={labelStyle}>{t('Мин.')}</label>
              <input type="number" min={15} max={480} step={15} value={durationMin} onChange={e => setDurationMin(Number(e.target.value))} style={inputStyle} required />
            </div>
          </div>
          <div className="kc-schedule-form-row" style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <label style={labelStyle}>{t('Зал')}</label>
              <Dropdown
                variant="field"
                width="100%"
                value={roomId}
                onChange={setRoomId}
                placeholder={t('Выберите зал')}
                searchable
                searchPlaceholder={t('Введите название зала')}
                options={[['', t('Выберите зал')], ...rooms.map(r => [String(r.id), r.name])]}
              />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <label style={labelStyle}>{t('Преподаватель')}</label>
              <Dropdown
                variant="field"
                width="100%"
                value={teacherId}
                onChange={setTeacherId}
                placeholder={t('Выберите преподавателя')}
                searchable
                searchPlaceholder={t('Введите имя преподавателя')}
                options={[['', t('Выберите преподавателя')], ...teachers.map(t => [String(t.id), t.full_name])]}
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
              <button type="button" style={secondaryBtn} onClick={onClose}>{t('Отмена')}</button>
              <button type="submit" style={primaryBtn} disabled={saving}>
                {saving ? t('Создание…') : (<><Plus size={14} />{t('Создать')}</>)}
              </button>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
