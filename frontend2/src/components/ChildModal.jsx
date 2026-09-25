import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { X, Camera, Upload } from 'lucide-react'
registerLocale('ru', ru)
import { registerLocale } from 'react-datepicker'
import ru from 'date-fns/locale/ru'

const inp = {
  width: '100%',
  padding: '10px 14px',
  border: '1px solid #E5E7EB',
  borderRadius: 8,
  fontSize: 13,
  fontFamily: 'Manrope',
  outline: 'none',
  background: '#FAFAFA',
  boxSizing: 'border-box',
}

const lbl = {
  display: 'block',
  fontSize: 11,
  fontWeight: 600,
  color: '#9CA3AF',
  marginBottom: 6,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
}

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

// child prop — если передан, режим редактирования (PATCH), иначе создание (POST)
export default function ChildModal({ onClose, onSaved, child }) {
  const isEdit = !!child

  const [form, setForm] = useState({
    full_name:          isEdit ? (child.full_name || '')     : '',
    birth_date:         isEdit ? (child.birth_date || '')    : '',
    birth_date_display: isEdit && child.birth_date
      ? child.birth_date.split('-').reverse().join('.')
      : '',
    gender:             isEdit ? (child.gender || '')        : '',
    status:             isEdit ? (child.status || 'active')  : 'active',
    directions:         isEdit ? (child.directions || [])    : [],
    medical_notes:      isEdit ? (child.medical_notes || '') : '',
    consent_given:      isEdit ? (child.consent_given || false) : false,
    leave_reason:       isEdit ? (child.leave_reason || '')  : '',
  })
  const [directionsList, setDirectionsList] = useState([])
  const [loading, setLoading]   = useState(false)
  const [errors, setErrors]     = useState({})
  const [photoPreview, setPhotoPreview] = useState(child?.photo_url || null)
  const fileRef = useRef()

  useEffect(() => {
    axios.get('/api/v1/directions/', { headers: authHeaders() })
      .then(r => setDirectionsList(r.data.results || r.data))
      .catch(() => {})
  }, [])

  function set(key, value) {
    setForm(f => ({ ...f, [key]: value }))
  }

  function toggleDirection(id) {
    setForm(f => ({
      ...f,
      directions: f.directions.includes(id)
        ? f.directions.filter(x => x !== id)
        : [...f.directions, id],
    }))
  }

  function handlePhotoChange(e) {
    const file = e.target.files[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => setPhotoPreview(ev.target.result)
    reader.readAsDataURL(file)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.gender)     { setErrors({ gender: 'Выберите пол' }); return }
    if (!form.birth_date) { setErrors({ birth_date: 'Укажите дату рождения' }); return }
    if (form.status === 'left' && !form.leave_reason.trim()) {
      setErrors({ leave_reason: 'Укажите причину ухода' }); return
    }
    setLoading(true); setErrors({})
    try {
      const payload = {
        full_name:     form.full_name,
        birth_date:    form.birth_date,
        gender:        form.gender,
        status:        form.status,
        directions:    form.directions,
        medical_notes: form.medical_notes,
        consent_given: form.consent_given,
        leave_reason:  form.leave_reason,
      }
      if (isEdit) {
        await axios.patch(`/api/v1/clients/children/${child.id}/`, payload, { headers: authHeaders() })
      } else {
        await axios.post('/api/v1/clients/children/', payload, { headers: authHeaders() })
      }
      onSaved()
    } catch (err) {
      setErrors(err.response?.data || { non_field_errors: 'Ошибка сервера' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
      onClick={onClose}
    >
      <div
        style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: 580, maxHeight: '92vh', overflowY: 'auto', padding: '28px 28px 24px' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>
            {isEdit ? 'Редактировать ребёнка' : 'Новый ребёнок'}
          </h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', display: 'flex' }}>
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Photo */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
            <div
              style={{ width: 72, height: 72, borderRadius: '50%', background: photoPreview ? 'transparent' : '#F8F9FF', border: '2px dashed #E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', overflow: 'hidden', flexShrink: 0 }}
              onClick={() => fileRef.current.click()}
            >
              {photoPreview
                ? <img src={photoPreview} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                : <Camera size={24} style={{ color: '#9CA3AF' }} />
              }
            </div>
            <div>
              <button
                type="button"
                onClick={() => fileRef.current.click()}
                style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff', cursor: 'pointer', fontSize: 13, fontFamily: 'Manrope', color: '#6B7280', marginBottom: 4 }}
              >
                <Upload size={14} /> Загрузить фото
              </button>
              <p style={{ fontSize: 11, color: '#9CA3AF', margin: 0 }}>JPG, PNG до 5 МБ</p>
            </div>
            <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handlePhotoChange} />
          </div>

          {/* ФИО + Дата */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={lbl}>ФИО *</label>
              <input
                style={{ ...inp, borderColor: errors.full_name ? '#DC2626' : '#E5E7EB' }}
                value={form.full_name}
                onChange={e => set('full_name', e.target.value)}
                placeholder="Введите ФИО"
                required
              />
              {errors.full_name && <p style={{ color: '#DC2626', fontSize: 11, margin: '4px 0 0' }}>{errors.full_name}</p>}
            </div>
            <div>
              <label style={lbl}>Дата рождения *</label>
              <div style={{ position: 'relative' }}>
                <input
                  placeholder="Введите дату рождения"
                  maxLength={10}
                  value={form.birth_date_display || ''}
                  onChange={e => {
                    let val = e.target.value.replace(/\D/g, '')
                    if (val.length > 2) val = val.slice(0,2) + '.' + val.slice(2)
                    if (val.length > 5) val = val.slice(0,5) + '.' + val.slice(5)
                    if (val.length > 10) val = val.slice(0,10)
                    set('birth_date_display', val)
                    const parts = val.split('.')
                    if (parts.length === 3 && parts[2].length === 4) {
                      set('birth_date', `${parts[2]}-${parts[1]}-${parts[0]}`)
                    } else {
                      set('birth_date', '')
                    }
                  }}
                  style={{ ...inp, borderColor: errors.birth_date ? '#DC2626' : '#E5E7EB', paddingRight: 40 }}
                />
                <svg viewBox="0 0 24 24" width="16" height="16" style={{ position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)', stroke: '#9CA3AF', fill: 'none', strokeWidth: 2, pointerEvents: 'none' }}>
                  <rect x="3" y="4" width="18" height="18" rx="2"/>
                  <line x1="16" y1="2" x2="16" y2="6"/>
                  <line x1="8" y1="2" x2="8" y2="6"/>
                  <line x1="3" y1="10" x2="21" y2="10"/>
                </svg>
              </div>
              {errors.birth_date && <p style={{ color: '#DC2626', fontSize: 11, margin: '4px 0 0' }}>{errors.birth_date}</p>}
            </div>
          </div>

          {/* Пол + Статус */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
            <div>
              <label style={lbl}>Пол *</label>
              <select style={{ ...inp, borderColor: errors.gender ? '#DC2626' : '#E5E7EB' }} value={form.gender} onChange={e => set('gender', e.target.value)} required>
                <option value="">Выберите пол</option>
                <option value="female">Женский</option>
                <option value="male">Мужской</option>
              </select>
              {errors.gender && <p style={{ color: '#DC2626', fontSize: 11, margin: '4px 0 0' }}>{errors.gender}</p>}
            </div>
            <div>
              <label style={lbl}>Статус</label>
              <select style={inp} value={form.status} onChange={e => set('status', e.target.value)}>
                <option value="active">Активен</option>
                <option value="frozen">Заморожен</option>
                <option value="left">Ушёл</option>
              </select>
            </div>
          </div>

          {/* Причина ухода */}
          {form.status === 'left' && (
            <div style={{ marginBottom: 16 }}>
              <label style={lbl}>Причина ухода *</label>
              <input style={{ ...inp, borderColor: errors.leave_reason ? '#DC2626' : '#E5E7EB' }} value={form.leave_reason} onChange={e => set('leave_reason', e.target.value)} required />
              {errors.leave_reason && <p style={{ color: '#DC2626', fontSize: 11, margin: '4px 0 0' }}>{errors.leave_reason}</p>}
            </div>
          )}

          {/* Направления */}
          {directionsList.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <label style={lbl}>Направления</label>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {directionsList.map(d => {
                  const active = form.directions.includes(d.id)
                  return (
                    <button key={d.id} type="button" onClick={() => toggleDirection(d.id)}
                      style={{ padding: '6px 14px', borderRadius: 20, cursor: 'pointer', border: `1px solid ${active ? '#E8998D' : '#E5E7EB'}`, background: active ? '#FDF0EE' : '#F8F9FF', fontSize: 12, fontWeight: 500, fontFamily: 'Manrope', color: active ? '#C97B6E' : '#6B7280' }}
                    >
                      {d.name}
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* Медицинские заметки */}
          <div style={{ marginBottom: 16 }}>
            <label style={lbl}>Медицинские заметки</label>
            <textarea style={{ ...inp, minHeight: 72, resize: 'vertical' }} value={form.medical_notes} onChange={e => set('medical_notes', e.target.value)} placeholder="Аллергии, особенности..." />
          </div>

          {/* Согласие */}
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24, cursor: 'pointer' }}>
            <input type="checkbox" checked={form.consent_given} onChange={e => set('consent_given', e.target.checked)} style={{ width: 16, height: 16, cursor: 'pointer' }} />
            <span style={{ fontSize: 13, color: '#6B7280' }}>Согласие на обработку данных получено</span>
          </label>

          {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{errors.non_field_errors}</p>}

          {/* Кнопки */}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={{ padding: '10px 22px', border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>
              Отмена
            </button>
            <button type="submit" disabled={loading} style={{ padding: '10px 22px', border: 'none', borderRadius: 8, background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: loading ? 0.7 : 1 }}>
              {loading ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать ребёнка'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
