import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowLeft, Plus, Edit2, Trash2, X } from 'lucide-react'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const lbl = { fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box', background: '#fff' }

function RoomModal({ branchId, room, onClose, onSaved }) {
  const isEdit = !!room
  const [name, setName] = useState(room?.name || '')
  const [capacity, setCapacity] = useState(room?.capacity ?? '')
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true); setErrors({})
    try {
      const payload = { name, branch: branchId, capacity: capacity === '' ? null : Number(capacity) }
      if (isEdit) {
        await axios.patch(`/api/v1/rooms/${room.id}/`, payload, { headers: authHeaders() })
      } else {
        await axios.post('/api/v1/rooms/', payload, { headers: authHeaders() })
      }
      onSaved()
    } catch (err) {
      setErrors(err.response?.data || { non_field_errors: 'Ошибка сервера' })
    } finally { setSaving(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }} onClick={onClose}>
      <div style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: 420, padding: '24px 24px 20px' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>{isEdit ? 'Редактировать зал' : 'Новый зал'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>
        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <div style={lbl}>Название зала *</div>
            <input value={name} onChange={e => setName(e.target.value)} required placeholder="Зал 1" style={inputStyle} />
            {errors.name && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.name[0]}</p>}
          </div>
          <div style={{ marginBottom: 18 }}>
            <div style={lbl}>Вместимость</div>
            <input type="number" min={1} value={capacity} onChange={e => setCapacity(e.target.value)} style={inputStyle} />
          </div>
          {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{errors.non_field_errors}</p>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={{ padding: '9px 18px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>Отмена</button>
            <button type="submit" disabled={saving} style={{ padding: '9px 18px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать зал'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function BranchRooms() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [branch, setBranch] = useState(null)
  const [rooms, setRooms] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editRoom, setEditRoom] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      axios.get(`/api/v1/branches/${id}/`, { headers: authHeaders() }),
      axios.get('/api/v1/rooms/', { headers: authHeaders(), params: { branch: id } }),
    ]).then(([b, r]) => {
      setBranch(b.data)
      const list = r.data.results || r.data
      setRooms(list.filter(room => String(room.branch) === String(id)))
    }).catch(console.error)
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { load() }, [load])

  async function handleDelete(room) {
    if (!window.confirm(`Удалить зал «${room.name}»?`)) return
    try {
      await axios.delete(`/api/v1/rooms/${room.id}/`, { headers: authHeaders() })
      load()
    } catch (e) { console.error(e) }
  }

  const card = { background: '#fff', borderRadius: 12, border: '1px solid #F0F0F5', overflow: 'hidden' }

  return (
    <div>
      <button onClick={() => navigate('/branches')}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', fontSize: 13, fontFamily: 'Manrope', marginBottom: 16, padding: 0 }}>
        <ArrowLeft size={14} /> К списку филиалов
      </button>

      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid #F0F0F5' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Залы {branch ? `— ${branch.name}` : ''}</h1>
          <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{rooms.length} залов</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }}
        >
          <Plus size={14} /> Новый зал
        </button>
      </div>

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #F0F0F5' }}>
              {['Название', 'Вместимость', ''].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={3} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</td></tr>
            ) : rooms.length === 0 ? (
              <tr><td colSpan={3} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Залов пока нет</td></tr>
            ) : rooms.map(room => (
              <tr key={room.id} style={{ borderBottom: '1px solid #F0F0F5' }}>
                <td style={{ padding: '14px 16px', fontSize: 13, fontWeight: 600, color: '#1A1A2E' }}>{room.name}</td>
                <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{room.capacity ?? '—'}</td>
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button onClick={() => setEditRoom(room)} title="Редактировать" style={iconBtnStyle}><Edit2 size={14} /></button>
                    <button onClick={() => handleDelete(room)} title="Удалить" style={{ ...iconBtnStyle, color: '#DC2626' }}><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(showModal || editRoom) && (
        <RoomModal
          branchId={id}
          room={editRoom}
          onClose={() => { setShowModal(false); setEditRoom(null) }}
          onSaved={() => { setShowModal(false); setEditRoom(null); load() }}
        />
      )}
    </div>
  )
}

const iconBtnStyle = {
  width: 30, height: 30, display: 'flex', alignItems: 'center', justifyContent: 'center',
  border: '1px solid #F0F0F5', borderRadius: 8, background: '#fff', cursor: 'pointer', color: '#6B7280',
}
