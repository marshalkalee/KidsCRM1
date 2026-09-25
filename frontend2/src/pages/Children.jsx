import { useState, useEffect, useRef, useCallback } from 'react'
import React from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Plus, Search, SlidersHorizontal, AlertCircle, X, ChevronDown, Check, Upload } from 'lucide-react'
import ChildModal from '../components/ChildModal'

const statusColors = {
  active: { bg: '#F0FDF4', color: '#16A34A', label: 'Активен' },
  frozen: { bg: '#EFF6FF', color: '#2563EB', label: 'Заморожен' },
  left:   { bg: '#F9FAFB', color: '#6B7280', label: 'Ушёл' },
}

function CustomSelect({ label, value, onChange, options }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const selected = options.find(([v]) => v === value)
  const active = value !== ''

  return (
    <div ref={ref} style={{ width: 160, flexShrink: 0, position: 'relative' }}>
      <div style={{
        fontSize: 10, fontWeight: 700, color: '#9CA3AF',
        textTransform: 'uppercase', letterSpacing: '0.07em',
        marginBottom: 5, fontFamily: 'Manrope',
      }}>{label}</div>

      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '7px 10px',
          border: `1.5px solid ${open ? '#E8998D' : active ? '#E8998D' : '#EBEBF0'}`,
          borderRadius: 8,
          background: active ? '#FDF0EE' : '#FAFAFA',
          fontSize: 12, fontFamily: 'Manrope', fontWeight: active ? 600 : 400,
          color: active ? '#C97B6E' : '#6B7280',
          cursor: 'pointer', outline: 'none',
          transition: 'border-color 0.15s, background 0.15s',
          boxShadow: open ? '0 0 0 3px rgba(201,123,110,0.12)' : 'none',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected ? selected[1] : options[0][1]}
        </span>
        <ChevronDown
          size={12}
          style={{ flexShrink: 0, marginLeft: 6, color: active ? '#C97B6E' : '#9CA3AF',
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
                  color: isSelected ? '#C97B6E' : '#374151',
                  background: isSelected ? '#FDF0EE' : '#fff',
                  cursor: 'pointer',
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = '#FAFAFA' }}
                onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '#fff' }}
              >
                {l}
                {isSelected && <Check size={12} style={{ color: '#C97B6E', flexShrink: 0 }} />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function CheckboxCard({ label, checked, onChange }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} style={{ display: 'none' }} />
      <div style={{
        width: 14, height: 14, flexShrink: 0, borderRadius: 4,
        border: `2px solid ${checked ? '#C97B6E' : '#D1D5DB'}`,
        background: checked ? '#C97B6E' : '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'all 0.15s',
      }}>
        {checked && (
          <svg width="8" height="6" viewBox="0 0 10 8" fill="none">
            <path d="M1 4L3.8 7L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
      </div>
      <span style={{ fontSize: 12, fontWeight: 600, color: checked ? '#C97B6E' : '#374151', fontFamily: 'Manrope', whiteSpace: 'nowrap' }}>
        {label}
      </span>
    </label>
  )
}

const EMPTY_FILTERS = { status: '', branch: '', direction: '', group: '', has_debt: false, subscription_expiring: false }

export default function Children() {
  const [children, setChildren]       = useState([])
  const [loading, setLoading]         = useState(true)
  const [search, setSearch]           = useState('')
  // pendingFilters — то что видит пользователь в UI до применения
  const [pendingFilters, setPendingFilters] = useState(EMPTY_FILTERS)
  // appliedFilters — то что реально уходит в запрос
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS)
  const [branches, setBranches]       = useState([])
  const [directions, setDirections]   = useState([])
  const [groups, setGroups]           = useState([])
  const [showFilters, setShowFilters] = useState(false)
  const [showModal, setShowModal]     = useState(false)
  const [showImport, setShowImport]   = useState(false)
  const navigate = useNavigate()

  // Справочники грузим один раз
  useEffect(() => {
    const token = localStorage.getItem('access')
    const headers = { Authorization: `Bearer ${token}` }
    Promise.all([
      axios.get('/api/v1/branches/',   { headers }),
      axios.get('/api/v1/groups/',     { headers }),
      axios.get('/api/v1/directions/', { headers }),
    ]).then(([b, g, d]) => {
      setBranches(b.data.results   || b.data)
      setGroups(g.data.results     || g.data)
      setDirections(d.data.results || d.data)
    }).catch(console.error)
  }, [])

  // Данные грузим только когда применены фильтры
  useEffect(() => { loadChildren() }, [appliedFilters])

  async function loadChildren() {
    setLoading(true)
    try {
      const token = localStorage.getItem('access')
      const headers = { Authorization: `Bearer ${token}` }
      const params = {}
      if (appliedFilters.status)                params.status = appliedFilters.status
      if (appliedFilters.branch)                params.branch = appliedFilters.branch
      if (appliedFilters.direction)             params.direction = appliedFilters.direction
      if (appliedFilters.group)                 params.group = appliedFilters.group
      if (appliedFilters.has_debt)              params.has_debt = true
      if (appliedFilters.subscription_expiring) params.subscription_expiring = true
      if (search)                               params.search = search

      const res = await axios.get('/api/v1/clients/children/', { headers, params })
      setChildren(res.data.results || res.data)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  function setPending(key, value) {
    setPendingFilters(f => ({ ...f, [key]: value }))
  }

  function applyFilters() {
    setAppliedFilters({ ...pendingFilters })
  }

  function resetFilters() {
    setPendingFilters(EMPTY_FILTERS)
    setAppliedFilters(EMPTY_FILTERS)
  }

  function handleSearch(e) {
    e.preventDefault()
    loadChildren()
  }

  const activeCount = [appliedFilters.status, appliedFilters.branch, appliedFilters.direction, appliedFilters.group, appliedFilters.has_debt, appliedFilters.subscription_expiring].filter(Boolean).length
  const hasPendingChanges = JSON.stringify(pendingFilters) !== JSON.stringify(appliedFilters)

  const card = { background: '#fff', borderRadius: 12, border: '1px solid #F0F0F5', overflow: 'hidden' }

  return (
    <div>
      {/* Header */}
      <div style={{
        background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        border: '1px solid #F0F0F5',
      }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Дети</h1>
          <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{children.length} учеников в базе</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => setShowImport(true)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
              background: '#fff', border: '1.5px solid #EBEBF0', borderRadius: 8,
              fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280',
            }}
          >
            <Upload size={14} /> Импорт из Excel
          </button>
          <button
            onClick={() => setShowModal(true)}
            style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
              background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
              color: '#fff', border: 'none', borderRadius: 8,
              fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
            }}
          >
            <Plus size={14} /> Добавить ребёнка
          </button>
        </div>
      </div>

      {/* Search + Filter toggle */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        <form onSubmit={handleSearch} style={{ flex: 1, display: 'flex' }}>
          <div style={{
            flex: 1, display: 'flex', alignItems: 'center', gap: 10,
            background: '#fff', border: '1px solid #F0F0F5', borderRadius: 10, padding: '10px 14px',
          }}>
            <Search size={16} style={{ color: '#9CA3AF', flexShrink: 0 }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Поиск по имени, телефону..."
              style={{ border: 'none', outline: 'none', fontSize: 13, width: '100%', fontFamily: 'Manrope' }}
            />
          </div>
        </form>
        <button
          onClick={() => setShowFilters(!showFilters)}
          style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px',
            background: showFilters ? '#FDF0EE' : '#fff',
            color: showFilters ? '#C97B6E' : '#6B7280',
            border: `1.5px solid ${showFilters ? '#E8998D' : '#F0F0F5'}`,
            borderRadius: 10, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
            position: 'relative',
          }}
        >
          <SlidersHorizontal size={15} />
          Фильтры
          {activeCount > 0 && (
            <span style={{
              position: 'absolute', top: -7, right: -7,
              width: 18, height: 18, borderRadius: '50%',
              background: '#C97B6E', color: '#fff',
              fontSize: 10, fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>{activeCount}</span>
          )}
        </button>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div style={{ ...card, padding: '16px 20px', marginBottom: 16, overflow: 'visible' }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end' }}>

            {/* Дропдауны */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <CustomSelect
                label="Филиал"
                value={pendingFilters.branch}
                onChange={v => setPending('branch', v)}
                options={[['', 'Все филиалы'], ...branches.map(b => [String(b.id), b.name])]}
              />
              <CustomSelect
                label="Направление"
                value={pendingFilters.direction}
                onChange={v => setPending('direction', v)}
                options={[['', 'Все направления'], ...directions.map(d => [String(d.id), d.name])]}
              />
              <CustomSelect
                label="Группа"
                value={pendingFilters.group}
                onChange={v => setPending('group', v)}
                options={[['', 'Все группы'], ...groups.map(g => [String(g.id), g.name])]}
              />
              <CustomSelect
                label="Статус"
                value={pendingFilters.status}
                onChange={v => setPending('status', v)}
                options={[['', 'Все статусы'], ['active', 'Активен'], ['frozen', 'Заморожен'], ['left', 'Ушёл']]}
              />
            </div>

            {/* Разделитель */}
            <div style={{ width: 1, height: 52, background: '#EBEBF0', flexShrink: 0 }} />

            {/* Чекбоксы столбиком */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingBottom: 2 }}>
              <CheckboxCard
                label="Есть задолженность"
                checked={pendingFilters.has_debt}
                onChange={v => setPending('has_debt', v)}
              />
              <CheckboxCard
                label="Абонемент скоро заканчивается"
                checked={pendingFilters.subscription_expiring}
                onChange={v => setPending('subscription_expiring', v)}
              />
            </div>

            {/* Кнопки применить / сбросить */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginLeft: 'auto', paddingBottom: 2 }}>
              <button
                onClick={applyFilters}
                disabled={!hasPendingChanges}
                style={{
                  padding: '7px 16px',
                  background: hasPendingChanges ? 'linear-gradient(135deg, #E8998D, #C97B6E)' : '#F0F0F5',
                  color: hasPendingChanges ? '#fff' : '#9CA3AF',
                  border: 'none', borderRadius: 8,
                  fontSize: 12, fontWeight: 600, cursor: hasPendingChanges ? 'pointer' : 'default',
                  fontFamily: 'Manrope', whiteSpace: 'nowrap',
                  transition: 'all 0.15s',
                }}
              >
                Применить
              </button>
              {(activeCount > 0 || hasPendingChanges) && (
                <button
                  onClick={resetFilters}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4,
                    padding: '7px 16px',
                    border: '1.5px solid #EBEBF0', borderRadius: 8,
                    background: '#fff', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer', fontFamily: 'Manrope', color: '#9CA3AF',
                    whiteSpace: 'nowrap',
                  }}
                >
                  <X size={11} /> Сбросить
                </button>
              )}
            </div>

          </div>
        </div>
      )}

      {/* Table */}
      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #F0F0F5' }}>
              {['ФИО', 'Возраст', 'Филиал', 'Группа', 'Статус', 'Абонемент', 'Долг'].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</td></tr>
            ) : children.length === 0 ? (
              <tr><td colSpan={7} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Детей пока нет</td></tr>
            ) : children.map(child => {
              const st = statusColors[child.status] || statusColors.active
              return (
                <tr
                  key={child.id}
                  onClick={() => navigate(`/children/${child.id}`)}
                  style={{ borderBottom: '1px solid #F0F0F5', cursor: 'pointer', transition: 'background 0.1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#FAFAFA'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '14px 16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{
                        width: 32, height: 32, borderRadius: '50%',
                        background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                      }}>
                        <span style={{ color: '#fff', fontSize: 12, fontWeight: 700 }}>{child.full_name?.charAt(0)}</span>
                      </div>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E' }}>{child.full_name}</span>
                    </div>
                  </td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{child.age || '—'}</td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{child.branch_name || '—'}</td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{child.group_name || '—'}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: st.bg, color: st.color }}>
                      {st.label}
                    </span>
                  </td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>
                    {child.subscription_remaining != null ? `${child.subscription_remaining} зан.` : '—'}
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    {child.debt > 0 ? (
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#DC2626', fontSize: 13, fontWeight: 600 }}>
                        <AlertCircle size={14} />
                        {child.debt?.toLocaleString()} ₸
                      </span>
                    ) : <span style={{ color: '#9CA3AF', fontSize: 13 }}>—</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {showModal && (
        <ChildModal
          onClose={() => setShowModal(false)}
          onSaved={() => { setShowModal(false); loadChildren() }}
        />
      )}

      {showImport && (
        <ImportModal
          onClose={() => setShowImport(false)}
          onSaved={() => { setShowImport(false); loadChildren() }}
        />
      )}
    </div>
  )
}

// Импорт — тот же жизненный цикл, что у веб-экрана импорта (backend:
// domains/people/clients/import_jobs.py): файл → сухой прогон в фоне (без
// записи в базу) → отчёт и решения по найденным дублям → импорт одной
// транзакцией → итог. Значения строк здесь не правятся: ошибки исправляются
// в самом файле и он загружается заново (ТЗ п. 4.1, TRU-36).
const IMPORT_API = '/api/v1/clients/children/import'
const LEVEL_STYLE = {
  ready:   ['#F0FDF4', '#16A34A', 'Готово'],
  warning: ['#FEF3C7', '#D97706', 'Предупреждение'],
  error:   ['#FEE2E2', '#DC2626', 'Ошибка'],
}

function ImportModal({ onClose, onSaved }) {
  const [file, setFile]             = useState(null)
  const [dryRun, setDryRun]         = useState(null)   // готовый сухой прогон
  const [decisions, setDecisions]   = useState({})     // {номер строки: create_new|attach|skip}
  const [waiting, setWaiting]       = useState('')     // текст ожидания фоновой задачи
  const [result, setResult]         = useState(null)   // итог импорта
  const [error, setError]           = useState('')
  const fileRef = useRef()

  function authHeaders() {
    return { Authorization: `Bearer ${localStorage.getItem('access')}` }
  }

  // Сухой прогон и импорт идут в фоне — опрашиваем статус задачи.
  async function waitForJob(jobId, label) {
    for (;;) {
      const res = await axios.get(`${IMPORT_API}/jobs/${jobId}/`, { headers: authHeaders() })
      const job = res.data
      if (job.status === 'done') return job
      if (job.status === 'failed') throw new Error(job.error_message || 'Ошибка задачи импорта')
      const p = job.progress
      setWaiting(p ? `${label}: ${p.done} / ${p.total}` : `${label}...`)
      await new Promise(resolve => setTimeout(resolve, 1500))
    }
  }

  async function handleUpload(e) {
    e.preventDefault()
    if (!file) return
    setError(''); setWaiting('Загрузка файла...')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await axios.post(`${IMPORT_API}/preview/`, fd, {
        headers: { ...authHeaders(), 'Content-Type': 'multipart/form-data' },
      })
      const job = await waitForJob(res.data.job_id, 'Проверка файла')
      const defaults = {}
      job.rows.forEach(r => { if (r.duplicate) defaults[r.row_number] = r.duplicate.options[0] })
      setDecisions(defaults)
      setDryRun(job)
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.file?.[0] || err.message || 'Ошибка загрузки файла')
    } finally { setWaiting('') }
  }

  async function handleConfirm() {
    setError(''); setWaiting('Запуск импорта...')
    try {
      const res = await axios.post(`${IMPORT_API}/confirm/`,
        { job_id: dryRun.job_id, decisions }, { headers: authHeaders() })
      setResult(await waitForJob(res.data.job_id, 'Запись в базу'))
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Ошибка импорта')
    } finally { setWaiting('') }
  }

  const lbl = { display: 'block', fontSize: 11, fontWeight: 600, color: '#9CA3AF', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.06em' }
  const btnPrimary = { padding: '10px 22px', border: 'none', borderRadius: 8, background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }
  const btnSecondary = { padding: '10px 22px', border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }
  const importable = dryRun ? dryRun.ready_count + dryRun.warning_count : 0

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }} onClick={onClose}>
      <div style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: result ? 480 : dryRun ? 960 : 560, maxHeight: '92vh', overflowY: 'auto', padding: '28px 28px 24px' }} onClick={e => e.stopPropagation()}>

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>
            {result ? 'Результат импорта' : dryRun ? 'Проверка файла' : 'Импорт из Excel'}
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', display: 'flex' }}><X size={20} /></button>
        </div>

        {waiting && <p style={{ fontSize: 13, fontFamily: 'Manrope', color: '#6B7280', marginBottom: 16 }}>{waiting}</p>}

        {/* Результат */}
        {result && (
          <div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 24 }}>
              {[
                ['Создано детей', result.children_created, '#F0FDF4', '#16A34A'],
                ['Создано родителей', result.parents_created, '#F0FDF4', '#16A34A'],
                ['Привязано к существующим родителям', result.attached_to_existing_parent, '#EFF6FF', '#2563EB'],
                ['Привязано к существующим детям', result.linked_to_existing_child, '#EFF6FF', '#2563EB'],
                ['Записано в группы', result.enrolled_in_groups, '#EFF6FF', '#2563EB'],
                ['Пропущено', result.skipped, '#F9FAFB', '#6B7280'],
              ].map(([label, val, bg, color]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', background: bg, borderRadius: 10 }}>
                  <span style={{ fontSize: 13, fontFamily: 'Manrope', color: '#374151' }}>{label}</span>
                  <span style={{ fontSize: 16, fontWeight: 700, fontFamily: 'Manrope', color }}>{val}</span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button onClick={onSaved} style={btnPrimary}>Готово</button>
            </div>
          </div>
        )}

        {/* Отчёт сухого прогона и решения по дублям */}
        {!result && dryRun && (
          <div>
            <p style={{ fontSize: 13, fontFamily: 'Manrope', color: '#374151', marginBottom: 16 }}>
              Готово: <b>{dryRun.ready_count}</b> · С предупреждениями: <b>{dryRun.warning_count}</b> · С ошибками (не будут импортированы): <b>{dryRun.error_count}</b>
            </p>
            <div style={{ overflowX: 'auto', marginBottom: 20 }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'Manrope' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid #F0F0F5', background: '#FAFAFA' }}>
                    {['Строка', 'Статус', 'ФИО ребёнка', 'Сообщения', 'Совпадение', 'Решение'].map(h => (
                      <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {dryRun.rows.map(row => {
                    const [bg, color, label] = LEVEL_STYLE[row.level]
                    const dup = row.duplicate
                    return (
                      <tr key={row.row_number} style={{ borderBottom: '1px solid #F0F0F5' }}>
                        <td style={{ padding: '8px 10px', color: '#9CA3AF', fontSize: 11 }}>{row.row_number}</td>
                        <td style={{ padding: '8px 10px' }}>
                          <span style={{ padding: '2px 8px', borderRadius: 5, background: bg, color, fontSize: 11, fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</span>
                        </td>
                        <td style={{ padding: '8px 10px' }}>{row.child_name || '—'}</td>
                        <td style={{ padding: '8px 10px', color: '#6B7280' }}>{row.messages.join('; ')}</td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{dup ? `${dup.kind_label}: ${dup.matched}` : '—'}</td>
                        <td style={{ padding: '8px 10px', minWidth: 200 }}>
                          {dup && (
                            <CustomSelect
                              value={decisions[row.row_number]}
                              onChange={v => setDecisions(d => ({ ...d, [row.row_number]: v }))}
                              options={dup.options.map(o => [o, dup.option_labels[o]])}
                            />
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{error}</p>}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setDryRun(null)} style={btnSecondary}>Назад</button>
              <button onClick={handleConfirm} disabled={!!waiting || !importable} style={{ ...btnPrimary, opacity: (waiting || !importable) ? 0.7 : 1 }}>
                {`Импортировать (${importable})`}
              </button>
            </div>
          </div>
        )}

        {/* Загрузка файла */}
        {!result && !dryRun && (
          <form onSubmit={handleUpload}>
            <div style={{ background: '#F8F9FF', border: '1px solid #E5E7EB', borderRadius: 10, padding: '14px 16px', marginBottom: 20, fontSize: 13, color: '#6B7280', fontFamily: 'Manrope', lineHeight: 1.8 }}>
              Файл .xlsx или .csv (первая строка — заголовки). Колонки узнаются по названию:
              <ul style={{ margin: '8px 0 0', paddingLeft: 18 }}>
                <li>ФИО ребёнка, дата рождения, пол — обязательно</li>
                <li>ФИО родителя, телефон родителя — обязательно</li>
                <li>Роль родителя, медицинские заметки, направление, группа — необязательно</li>
              </ul>
              Сначала файл проверяется без записи в базу — вы увидите ошибки и найденные дубли.
            </div>

            <div style={{ marginBottom: 20 }}>
              <label style={lbl}>Файл (.xlsx, .csv) *</label>
              <div
                onClick={() => fileRef.current.click()}
                style={{
                  border: `2px dashed ${file ? '#E8998D' : '#E5E7EB'}`,
                  borderRadius: 10, padding: '24px 16px',
                  textAlign: 'center', cursor: 'pointer',
                  background: file ? '#FDF0EE' : '#FAFAFA',
                  transition: 'all 0.15s',
                }}
              >
                <Upload size={24} style={{ color: file ? '#C97B6E' : '#9CA3AF', marginBottom: 8 }} />
                <div style={{ fontSize: 13, fontFamily: 'Manrope', color: file ? '#C97B6E' : '#6B7280', fontWeight: file ? 600 : 400 }}>
                  {file ? file.name : 'Нажмите чтобы выбрать файл'}
                </div>
              </div>
              <input ref={fileRef} type="file" accept=".xlsx,.csv" style={{ display: 'none' }} onChange={e => setFile(e.target.files[0])} />
            </div>

            {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{error}</p>}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} style={btnSecondary}>Отмена</button>
              <button type="submit" disabled={!file || !!waiting} style={{ ...btnPrimary, opacity: (!file || waiting) ? 0.7 : 1 }}>
                {waiting ? 'Проверка...' : 'Загрузить и проверить'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
