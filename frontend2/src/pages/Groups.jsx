import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Plus, Search, SlidersHorizontal, ChevronDown, Check, X, Users } from 'lucide-react'
import GroupModal from '../components/GroupModal'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const STATUS_STYLE = {
  active: { bg: '#F0FDF4', color: '#16A34A', label: 'Активна' },
  paused: { bg: '#FFFBEB', color: '#D97706', label: 'Приостановлена' },
  closed: { bg: '#F9FAFB', color: '#6B7280', label: 'Закрыта' },
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
    <div ref={ref} style={{ width: 170, flexShrink: 0, position: 'relative' }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }}>{label}</div>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '7px 10px',
          border: `1.5px solid ${open || active ? '#E8998D' : '#EBEBF0'}`,
          borderRadius: 8, background: active ? '#FDF0EE' : '#FAFAFA',
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
        <ChevronDown size={12} style={{ flexShrink: 0, marginLeft: 6, color: active ? '#C97B6E' : '#9CA3AF', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }} />
      </button>

      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 100, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', overflow: 'hidden' }}>
          {options.map(([v, l]) => {
            const isSelected = value === v
            return (
              <div
                key={v}
                onClick={() => { onChange(v); setOpen(false) }}
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 12px', fontSize: 12, fontFamily: 'Manrope', fontWeight: isSelected ? 600 : 400, color: isSelected ? '#C97B6E' : '#374151', background: isSelected ? '#FDF0EE' : '#fff', cursor: 'pointer' }}
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

const EMPTY_FILTERS = { status: '', branch: '', direction: '' }

export default function Groups() {
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [pendingFilters, setPendingFilters] = useState(EMPTY_FILTERS)
  const [appliedFilters, setAppliedFilters] = useState(EMPTY_FILTERS)
  const [branches, setBranches] = useState([])
  const [directions, setDirections] = useState([])
  const [showFilters, setShowFilters] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    Promise.all([
      axios.get('/api/v1/branches/', { headers: authHeaders() }),
      axios.get('/api/v1/directions/', { headers: authHeaders() }),
    ]).then(([b, d]) => {
      setBranches(b.data.results || b.data)
      setDirections(d.data.results || d.data)
    }).catch(console.error)
  }, [])

  useEffect(() => { loadGroups() }, [appliedFilters])

  async function loadGroups() {
    setLoading(true)
    try {
      const params = {}
      if (appliedFilters.status) params.status = appliedFilters.status
      if (appliedFilters.branch) params.branch = appliedFilters.branch
      if (appliedFilters.direction) params.direction = appliedFilters.direction
      if (search) params.search = search
      const res = await axios.get('/api/v1/groups/', { headers: authHeaders(), params })
      setGroups(res.data.results || res.data)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  function setPending(key, value) { setPendingFilters(f => ({ ...f, [key]: value })) }
  function applyFilters() { setAppliedFilters({ ...pendingFilters }) }
  function resetFilters() { setPendingFilters(EMPTY_FILTERS); setAppliedFilters(EMPTY_FILTERS) }
  function handleSearch(e) { e.preventDefault(); loadGroups() }

  const activeCount = [appliedFilters.status, appliedFilters.branch, appliedFilters.direction].filter(Boolean).length
  const hasPendingChanges = JSON.stringify(pendingFilters) !== JSON.stringify(appliedFilters)
  const card = { background: '#fff', borderRadius: 12, border: '1px solid #F0F0F5', overflow: 'hidden' }

  return (
    <div>
      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid #F0F0F5' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Группы</h1>
          <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{groups.length} групп</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }}
        >
          <Plus size={14} /> Новая группа
        </button>
      </div>

      <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        <form onSubmit={handleSearch} style={{ flex: 1, display: 'flex' }}>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10, background: '#fff', border: '1px solid #F0F0F5', borderRadius: 10, padding: '10px 14px' }}>
            <Search size={16} style={{ color: '#9CA3AF', flexShrink: 0 }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Поиск по названию, направлению, филиалу..."
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
            <span style={{ position: 'absolute', top: -7, right: -7, width: 18, height: 18, borderRadius: '50%', background: '#C97B6E', color: '#fff', fontSize: 10, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{activeCount}</span>
          )}
        </button>
      </div>

      {showFilters && (
        <div style={{ ...card, padding: '16px 20px', marginBottom: 16, overflow: 'visible' }}>
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end' }}>
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
                label="Статус"
                value={pendingFilters.status}
                onChange={v => setPending('status', v)}
                options={[['', 'Все статусы'], ...Object.entries(STATUS_STYLE).map(([v, s]) => [v, s.label])]}
              />
            </div>
            <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
              <button
                onClick={applyFilters}
                disabled={!hasPendingChanges}
                style={{ padding: '7px 16px', background: hasPendingChanges ? 'linear-gradient(135deg, #E8998D, #C97B6E)' : '#F0F0F5', color: hasPendingChanges ? '#fff' : '#9CA3AF', border: 'none', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: hasPendingChanges ? 'pointer' : 'default', fontFamily: 'Manrope', whiteSpace: 'nowrap' }}
              >
                Применить
              </button>
              {(activeCount > 0 || hasPendingChanges) && (
                <button
                  onClick={resetFilters}
                  style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '7px 16px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', color: '#9CA3AF', whiteSpace: 'nowrap' }}
                >
                  <X size={11} /> Сбросить
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #F0F0F5' }}>
              {['Название', 'Филиал', 'Направление', 'Преподаватели', 'Записано', 'Статус'].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</td></tr>
            ) : groups.length === 0 ? (
              <tr><td colSpan={6} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Групп пока нет</td></tr>
            ) : groups.map(group => {
              const st = STATUS_STYLE[group.status] || STATUS_STYLE.active
              const branch = branches.find(b => String(b.id) === String(group.branch))
              const direction = directions.find(d => String(d.id) === String(group.direction))
              const full = group.members_count >= group.capacity
              return (
                <tr
                  key={group.id}
                  onClick={() => navigate(`/groups/${group.id}`)}
                  style={{ borderBottom: '1px solid #F0F0F5', cursor: 'pointer', transition: 'background 0.1s' }}
                  onMouseEnter={e => e.currentTarget.style.background = '#FAFAFA'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '14px 16px', fontSize: 13, fontWeight: 600, color: '#1A1A2E' }}>{group.name}</td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{branch?.name || '—'}</td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{direction?.name || '—'}</td>
                  <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{group.teachers_count || 0}</td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 13, fontWeight: 600, color: full ? '#D97706' : '#1A1A2E' }}>
                      <Users size={13} style={{ color: '#9CA3AF' }} />
                      {group.members_count} / {group.capacity}
                    </span>
                  </td>
                  <td style={{ padding: '14px 16px' }}>
                    <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: st.bg, color: st.color }}>{st.label}</span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {showModal && (
        <GroupModal
          onClose={() => setShowModal(false)}
          onSaved={() => { setShowModal(false); loadGroups() }}
        />
      )}
    </div>
  )
}
