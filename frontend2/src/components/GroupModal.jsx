import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { X, ChevronDown, Check } from 'lucide-react'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const STATUS_LABEL = { active: 'Активна', paused: 'Приостановлена', closed: 'Закрыта' }

const lbl = { fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box', background: '#fff' }

function CustomSelect({ label, value, onChange, options, placeholder }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    function h(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const selected = options.find(([v]) => v === value)
  const active = !!value

  return (
    <div ref={ref} style={{ position: 'relative', width: '100%' }}>
      {label && <div style={lbl}>{label}</div>}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 12px',
          border: `1.5px solid ${open || active ? '#E8998D' : '#EBEBF0'}`,
          borderRadius: 8, background: active ? '#FDF0EE' : '#FAFAFA',
          fontSize: 13, fontFamily: 'Manrope', fontWeight: active ? 600 : 400,
          color: active ? '#C97B6E' : '#9CA3AF',
          cursor: 'pointer', outline: 'none',
          boxShadow: open ? '0 0 0 3px rgba(201,123,110,0.12)' : 'none',
          transition: 'all 0.15s',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected ? selected[1] : (placeholder || 'Выберите...')}
        </span>
        <ChevronDown size={13} style={{ flexShrink: 0, marginLeft: 6, color: active ? '#C97B6E' : '#9CA3AF', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 200, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', overflow: 'hidden', maxHeight: 240, overflowY: 'auto' }}>
          {options.map(([v, l]) => {
            const isSel = value === v
            return (
              <div key={v} onClick={() => { onChange(v); setOpen(false) }}
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', fontSize: 13, fontFamily: 'Manrope', fontWeight: isSel ? 600 : 400, color: isSel ? '#C97B6E' : '#374151', background: isSel ? '#FDF0EE' : '#fff', cursor: 'pointer' }}
                onMouseEnter={e => { if (!isSel) e.currentTarget.style.background = '#FAFAFA' }}
                onMouseLeave={e => { if (!isSel) e.currentTarget.style.background = '#fff' }}
              >
                {l}
                {isSel && <Check size={13} style={{ color: '#C97B6E' }} />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function TeachersMultiSelect({ label, value, onChange, options }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    function h(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function toggle(id) {
    onChange(value.includes(id) ? value.filter(v => v !== id) : [...value, id])
  }

  const active = value.length > 0
  const summary = active
    ? options.filter(([v]) => value.includes(v)).map(([, l]) => l).join(', ')
    : 'Не назначены'

  return (
    <div ref={ref} style={{ position: 'relative', width: '100%' }}>
      {label && <div style={lbl}>{label}</div>}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 12px',
          border: `1.5px solid ${open || active ? '#E8998D' : '#EBEBF0'}`,
          borderRadius: 8, background: active ? '#FDF0EE' : '#FAFAFA',
          fontSize: 13, fontFamily: 'Manrope', fontWeight: active ? 600 : 400,
          color: active ? '#C97B6E' : '#9CA3AF',
          cursor: 'pointer', outline: 'none', textAlign: 'left',
          boxShadow: open ? '0 0 0 3px rgba(201,123,110,0.12)' : 'none',
          transition: 'all 0.15s',
        }}
      >
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{summary}</span>
        <ChevronDown size={13} style={{ flexShrink: 0, marginLeft: 6, color: active ? '#C97B6E' : '#9CA3AF', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 200, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', overflow: 'hidden', maxHeight: 240, overflowY: 'auto' }}>
          {options.length === 0 ? (
            <div style={{ padding: '12px 14px', fontSize: 13, color: '#9CA3AF', fontFamily: 'Manrope' }}>Преподавателей нет</div>
          ) : options.map(([v, l]) => {
            const checked = value.includes(v)
            return (
              <div key={v} onClick={() => toggle(v)}
                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', fontSize: 13, fontFamily: 'Manrope', color: '#374151', cursor: 'pointer' }}
                onMouseEnter={e => e.currentTarget.style.background = '#FAFAFA'}
                onMouseLeave={e => e.currentTarget.style.background = '#fff'}
              >
                <div style={{ width: 16, height: 16, flexShrink: 0, borderRadius: 4, border: `2px solid ${checked ? '#C97B6E' : '#D1D5DB'}`, background: checked ? '#C97B6E' : '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  {checked && <svg width="9" height="7" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.8 7L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>}
                </div>
                {l}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function GroupModal({ group, onClose, onSaved }) {
  const isEdit = !!group
  const [branches, setBranches] = useState([])
  const [directions, setDirections] = useState([])
  const [teachers, setTeachers] = useState([])
  const [form, setForm] = useState({
    name: group?.name || '',
    branch: group?.branch != null ? String(group.branch) : '',
    direction: group?.direction != null ? String(group.direction) : '',
    teachers: (group?.teachers || []).map(String),
    capacity: group?.capacity ?? '',
    age_min: group?.age_min ?? '',
    age_max: group?.age_max ?? '',
    status: group?.status || 'active',
  })
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})

  useEffect(() => {
    Promise.all([
      axios.get('/api/v1/branches/', { headers: authHeaders() }),
      axios.get('/api/v1/directions/', { headers: authHeaders() }),
      axios.get('/api/v1/users/', { headers: authHeaders() }),
    ]).then(([b, d, u]) => {
      setBranches(b.data.results || b.data)
      setDirections(d.data.results || d.data)
      setTeachers((u.data.results || u.data).filter(x => x.role === 'teacher'))
    }).catch(console.error)
  }, [])

  function setField(key, value) { setForm(f => ({ ...f, [key]: value })) }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true); setErrors({})
    const payload = {
      name: form.name,
      branch: form.branch || null,
      direction: form.direction || null,
      teachers: form.teachers,
      capacity: Number(form.capacity),
      age_min: form.age_min === '' ? null : Number(form.age_min),
      age_max: form.age_max === '' ? null : Number(form.age_max),
      status: form.status,
    }
    try {
      if (isEdit) {
        await axios.patch(`/api/v1/groups/${group.id}/`, payload, { headers: authHeaders() })
      } else {
        await axios.post('/api/v1/groups/', payload, { headers: authHeaders() })
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
      <div style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: 520, maxHeight: '92vh', overflowY: 'auto', padding: '24px 24px 20px' }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>{isEdit ? 'Редактировать группу' : 'Новая группа'}</h2>
          <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
        </div>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 14 }}>
            <div style={lbl}>Название *</div>
            <input value={form.name} onChange={e => setField('name', e.target.value)} required placeholder="Балет — Младшая группа" style={inputStyle} />
            {errors.name && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.name[0]}</p>}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            <div>
              <CustomSelect
                label="Филиал *"
                value={form.branch}
                onChange={v => setField('branch', v)}
                options={branches.map(b => [String(b.id), b.name])}
                placeholder="Выберите филиал"
              />
              {errors.branch && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.branch[0]}</p>}
            </div>
            <div>
              <CustomSelect
                label="Направление *"
                value={form.direction}
                onChange={v => setField('direction', v)}
                options={directions.map(d => [String(d.id), d.name])}
                placeholder="Выберите направление"
              />
              {errors.direction && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.direction[0]}</p>}
            </div>
          </div>

          <div style={{ marginBottom: 14 }}>
            <TeachersMultiSelect
              label="Преподаватели"
              value={form.teachers}
              onChange={v => setField('teachers', v)}
              options={teachers.map(t => [String(t.id), t.full_name])}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 14, marginBottom: 14 }}>
            <div>
              <div style={lbl}>Вместимость *</div>
              <input type="number" min={1} value={form.capacity} onChange={e => setField('capacity', e.target.value)} required style={inputStyle} />
              {errors.capacity && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.capacity[0]}</p>}
            </div>
            <div>
              <div style={lbl}>Возраст от</div>
              <input type="number" min={0} value={form.age_min} onChange={e => setField('age_min', e.target.value)} style={inputStyle} />
            </div>
            <div>
              <div style={lbl}>Возраст до</div>
              <input type="number" min={0} value={form.age_max} onChange={e => setField('age_max', e.target.value)} style={inputStyle} />
              {errors.age_min && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0', gridColumn: '1 / -1' }}>{errors.age_min[0]}</p>}
            </div>
          </div>

          <div style={{ marginBottom: 18 }}>
            <CustomSelect
              label="Статус"
              value={form.status}
              onChange={v => setField('status', v)}
              options={Object.entries(STATUS_LABEL)}
            />
          </div>

          {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{errors.non_field_errors}</p>}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose} style={{ padding: '9px 18px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>Отмена</button>
            <button type="submit" disabled={saving} style={{ padding: '9px 18px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Сохранение...' : isEdit ? 'Сохранить' : 'Создать группу'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
