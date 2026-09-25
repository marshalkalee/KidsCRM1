import { useState, useEffect } from 'react'
import axios from 'axios'
import { Plus, Edit2, Archive, ArchiveRestore } from 'lucide-react'
import DirectionModal from '../components/DirectionModal'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

export default function Directions() {
  const [directions, setDirections] = useState([])
  const [branches, setBranches] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editDirection, setEditDirection] = useState(null)

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const [d, b] = await Promise.all([
        axios.get('/api/v1/directions/', { headers: authHeaders() }),
        axios.get('/api/v1/branches/', { headers: authHeaders() }),
      ])
      const list = d.data.results || d.data
      list.sort((a, b2) => Number(b2.is_active) - Number(a.is_active) || a.name.localeCompare(b2.name))
      setDirections(list)
      setBranches(b.data.results || b.data)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function toggleActive(direction) {
    try {
      await axios.patch(`/api/v1/directions/${direction.id}/`, { is_active: !direction.is_active }, { headers: authHeaders() })
      load()
    } catch (e) { console.error(e) }
  }

  function branchNames(direction) {
    const names = (direction.branches || []).map(id => branches.find(b => String(b.id) === String(id))?.name).filter(Boolean)
    return names.length ? names.join(', ') : '—'
  }

  const card = { background: '#fff', borderRadius: 12, border: '1px solid #F0F0F5', overflow: 'hidden' }

  return (
    <div>
      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid #F0F0F5' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Направления</h1>
          <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{directions.length} направлений</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }}
        >
          <Plus size={14} /> Новое направление
        </button>
      </div>

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #F0F0F5' }}>
              {['Название', 'Возраст', 'Филиалы', 'Статус', ''].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</td></tr>
            ) : directions.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Направлений пока нет</td></tr>
            ) : directions.map(direction => (
              <tr key={direction.id} style={{ borderBottom: '1px solid #F0F0F5', opacity: direction.is_active ? 1 : 0.55 }}>
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 12, height: 12, borderRadius: 4, background: direction.color, flexShrink: 0 }} />
                    <span style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E' }}>{direction.name}</span>
                  </div>
                </td>
                <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>
                  {direction.age_min || direction.age_max ? `${direction.age_min ?? '—'}–${direction.age_max ?? '—'} лет` : '—'}
                </td>
                <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{branchNames(direction)}</td>
                <td style={{ padding: '14px 16px' }}>
                  <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: direction.is_active ? '#F0FDF4' : '#F9FAFB', color: direction.is_active ? '#16A34A' : '#6B7280' }}>
                    {direction.is_active ? 'Активно' : 'В архиве'}
                  </span>
                </td>
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button onClick={() => setEditDirection(direction)} title="Редактировать" style={iconBtnStyle}><Edit2 size={14} /></button>
                    <button
                      onClick={() => toggleActive(direction)}
                      title={direction.is_active ? 'Архивировать' : 'Восстановить'}
                      style={iconBtnStyle}
                    >
                      {direction.is_active ? <Archive size={14} /> : <ArchiveRestore size={14} />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(showModal || editDirection) && (
        <DirectionModal
          direction={editDirection}
          onClose={() => { setShowModal(false); setEditDirection(null) }}
          onSaved={() => { setShowModal(false); setEditDirection(null); load() }}
        />
      )}
    </div>
  )
}

const iconBtnStyle = {
  width: 30, height: 30, display: 'flex', alignItems: 'center', justifyContent: 'center',
  border: '1px solid #F0F0F5', borderRadius: 8, background: '#fff', cursor: 'pointer', color: '#6B7280',
}
