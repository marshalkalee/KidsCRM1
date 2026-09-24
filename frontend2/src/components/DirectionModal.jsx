import { useState, useEffect } from 'react'
import axios from 'axios'
import { X } from 'lucide-react'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const lbl = { fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box', background: '#fff' }

export default function DirectionModal({ direction, onClose, onSaved }) {
  const isEdit = !!direction
  const [branches, setBranches] = useState([])
  const [name, setName] = useState(direction?.name || '')
  const [color, setColor] = useState(direction?.color || '#7C6FF7')
  const [ageMin, setAgeMin] = useState(direction?.age_min ?? '')
  const [ageMax, setAgeMax] = useState(direction?.age_max ?? '')
  const [selectedBranches, setSelectedBranches] = useState((direction?.branches || []).map(String))
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    axios.get('/api/v1/branches/', { headers: authHeaders() })
      .then(res => setBranches((res.data.results || res.data).filter(b => b.is_active)))
      .catch(console.error)
  }, [])

  function toggleBranch(id) {
    setSelectedBranches(list => list.includes(id) ? list.filter(v => v !== id) : [...list, id])
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true); setErrors({})
    try {
      const payload = {
        name,
        color,
        age_min: ageMin === '' ? null : Number(ageMin),
        age_max: ageMax === '' ? null : Number(ageMax),
        branches: selectedBranches,
      }
      if (isEdit) {
        await axios.patch(`/api/v1/directions/${direction.id}/`, payload, { headers: authHeaders() })
      } else {
        await axios.post('/api/v1/directions/', payload, { headers: authHeaders() })
      }
      onSaved()
    } catch (err) {
      setErrors(err.response?.data || { non_field_errors: 'Ошибка сервера' })
    } finally { setSaving(false) }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }} onClick={onClose}>
      <div style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: 480, maxHeight: '92vh', overflowY: 'auto', padding: '24px 24px 20px' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>{isEdit ? 'Редактировать направление' : 'Новое направление'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ display: 'flex', gap: 14, marginBottom: 14 }}>
            <div style={{ flex: 1 }}>
              <div style={lbl}>Название направления *</div>
              <input value={name} onChange={e => setName(e.target.value)} required placeholder="Балет" style={inputStyle} />
              {errors.name && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.name[0]}</p>}
            </div>
            <div style={{ width: 90 }}>
              <div style={lbl}>Цвет</div>
              <input type="color" value={color} onChange={e => setColor(e.target.value)} style={{ ...inputStyle, padding: 4, height: 38, cursor: 'pointer' }} />
            </div>
          </div>

          <div style={{ display: 'flex', gap: 14, marginBottom: 18 }}>
            <div style={{ flex: 1 }}>
              <div style={lbl}>Возраст от</div>
              <input type="number" min={0} value={ageMin} onChange={e => setAgeMin(e.target.value)} style={inputStyle} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={lbl}>Возраст до</div>
              <input type="number" min={0} value={ageMax} onChange={e => setAgeMax(e.target.value)} style={inputStyle} />
              {errors.age_max && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.age_max[0]}</p>}
            </div>
          </div>

          <div style={{ marginBottom: 18 }}>
            <div style={lbl}>Доступно в филиалах</div>
            {branches.length === 0 ? (
              <p style={{ fontSize: 12, color: '#9CA3AF', fontFamily: 'Manrope' }}>Нет активных филиалов</p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, background: '#FAFAFA', border: '1.5px solid #EBEBF0', borderRadius: 8, padding: '10px 12px' }}>
                {branches.map(b => {
                  const checked = selectedBranches.includes(String(b.id))
                  return (
                    <label key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none' }}>
                      <input type="checkbox" checked={checked} onChange={() => toggleBranch(String(b.id))} style={{ display: 'none' }} />
                      <div style={{ width: 16, height: 16, flexShrink: 0, borderRadius: 4, border: `2px solid ${checked ? '#C97B6E' : '#D1D5DB'}`, background: checked ? '#C97B6E' : '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        {checked && <svg width="9" height="7" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.8 7L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                      </div>
                      <span style={{ fontSize: 13, fontFamily: 'Manrope', color: '#374151' }}>{b.name}</span>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{errors.non_field_errors}</p>}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={{ padding: '9px 18px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>Отмена</button>
            <button type="submit" disabled={saving} style={{ padding: '9px 18px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать направление'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
