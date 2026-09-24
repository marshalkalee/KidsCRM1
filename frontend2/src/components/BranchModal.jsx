import { useState } from 'react'
import axios from 'axios'
import { X } from 'lucide-react'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const WEEKDAYS = [
  ['mon', 'Понедельник'],
  ['tue', 'Вторник'],
  ['wed', 'Среда'],
  ['thu', 'Четверг'],
  ['fri', 'Пятница'],
  ['sat', 'Суббота'],
  ['sun', 'Воскресенье'],
]

const lbl = { fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box', background: '#fff' }
const timeInputStyle = { ...inputStyle, padding: '6px 8px', fontSize: 12 }

function defaultWorkingHours() {
  const hours = {}
  WEEKDAYS.forEach(([code]) => {
    hours[code] = { closed: code === 'sat' || code === 'sun', open: '09:00', close: '20:00' }
  })
  return hours
}

export default function BranchModal({ branch, onClose, onSaved }) {
  const isEdit = !!branch
  const [name, setName] = useState(branch?.name || '')
  const [address, setAddress] = useState(branch?.address || '')
  const [phone, setPhone] = useState(branch?.phone || '')
  const [hours, setHours] = useState(() => {
    if (!branch?.working_hours || Object.keys(branch.working_hours).length === 0) return defaultWorkingHours()
    const merged = defaultWorkingHours()
    Object.entries(branch.working_hours).forEach(([code, day]) => {
      merged[code] = { closed: !!day.closed, open: day.open || '09:00', close: day.close || '20:00' }
    })
    return merged
  })
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})

  function setDay(code, patch) {
    setHours(h => ({ ...h, [code]: { ...h[code], ...patch } }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true); setErrors({})

    let hasError = false
    const dayErrors = {}
    const payloadHours = {}
    WEEKDAYS.forEach(([code]) => {
      const day = hours[code]
      if (day.closed) {
        payloadHours[code] = { closed: true }
      } else {
        if (day.open && day.close && day.close <= day.open) {
          dayErrors[code] = 'Время закрытия должно быть позже открытия.'
          hasError = true
        }
        payloadHours[code] = { closed: false, open: day.open, close: day.close }
      }
    })
    if (hasError) {
      setErrors({ working_hours: dayErrors })
      setSaving(false)
      return
    }

    try {
      const payload = { name, address, phone, working_hours: payloadHours }
      if (isEdit) {
        await axios.patch(`/api/v1/branches/${branch.id}/`, payload, { headers: authHeaders() })
      } else {
        await axios.post('/api/v1/branches/', payload, { headers: authHeaders() })
      }
      onSaved()
    } catch (err) {
      setErrors(err.response?.data || { non_field_errors: 'Ошибка сервера' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }} onClick={onClose}>
      <div style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: 560, maxHeight: '92vh', overflowY: 'auto', padding: '24px 24px 20px' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>{isEdit ? 'Редактировать филиал' : 'Новый филиал'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <div style={lbl}>Название филиала *</div>
            <input value={name} onChange={e => setName(e.target.value)} required placeholder="Центральный" style={inputStyle} />
            {errors.name && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.name[0]}</p>}
          </div>

          <div style={{ marginBottom: 14 }}>
            <div style={lbl}>Адрес</div>
            <textarea value={address} onChange={e => setAddress(e.target.value)} rows={2} style={{ ...inputStyle, resize: 'vertical' }} />
          </div>

          <div style={{ marginBottom: 20 }}>
            <div style={lbl}>Телефон</div>
            <input value={phone} onChange={e => setPhone(e.target.value)} placeholder="+7 700 000 00 00" style={inputStyle} />
          </div>

          <div style={{ fontSize: 14, fontWeight: 700, color: '#1A1A2E', fontFamily: 'Manrope', marginBottom: 10 }}>Часы работы</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
            {WEEKDAYS.map(([code, label]) => {
              const day = hours[code]
              return (
                <div key={code} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ width: 100, fontSize: 12, color: '#374151', fontFamily: 'Manrope', flexShrink: 0 }}>{label}</span>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', flexShrink: 0, width: 90 }}>
                    <input type="checkbox" checked={day.closed} onChange={e => setDay(code, { closed: e.target.checked })} style={{ display: 'none' }} />
                    <div style={{ width: 14, height: 14, borderRadius: 4, border: `2px solid ${day.closed ? '#C97B6E' : '#D1D5DB'}`, background: day.closed ? '#C97B6E' : '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {day.closed && <svg width="8" height="6" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.8 7L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                    </div>
                    <span style={{ fontSize: 12, color: '#6B7280', fontFamily: 'Manrope' }}>Выходной</span>
                  </label>
                  {!day.closed && (
                    <>
                      <input type="time" value={day.open} onChange={e => setDay(code, { open: e.target.value })} style={{ ...timeInputStyle, width: 100 }} />
                      <span style={{ color: '#9CA3AF' }}>—</span>
                      <input type="time" value={day.close} onChange={e => setDay(code, { close: e.target.value })} style={{ ...timeInputStyle, width: 100 }} />
                    </>
                  )}
                  {errors.working_hours?.[code] && (
                    <span style={{ color: '#DC2626', fontSize: 11, fontFamily: 'Manrope' }}>{errors.working_hours[code]}</span>
                  )}
                </div>
              )
            })}
          </div>

          {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{errors.non_field_errors}</p>}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={{ padding: '9px 18px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>Отмена</button>
            <button type="submit" disabled={saving} style={{ padding: '9px 18px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать филиал'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
