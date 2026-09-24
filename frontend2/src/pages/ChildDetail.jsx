import React from 'react'
import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import {
  ArrowLeft, Edit2, Plus, Trash2, X, Check,
  ChevronDown, Phone, MessageCircle, FileText, CheckCircle
} from 'lucide-react'
import ChildModal from '../components/ChildModal'
import DatePicker from 'react-datepicker'
import 'react-datepicker/dist/react-datepicker.css'

// ── helpers ───────────────────────────────────────────────────────────────────

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const statusColors = {
  active: { bg: '#F0FDF4', color: '#16A34A', label: 'Активен' },
  paused: { bg: '#FFF7E6', color: '#B7791F', label: 'Приостановлен' },
  left:   { bg: '#F9FAFB', color: '#6B7280', label: 'Ушёл' },
}

const genderLabel  = { male: 'Мужской', female: 'Женский' }
const roleLabel    = {
  mother: 'Мама', father: 'Папа', guardian: 'Опекун',
  grandmother: 'Бабушка', grandfather: 'Дедушка', other: 'Другое',
}
const channelLabel = { call: 'Звонок', whatsapp: 'WhatsApp', comment: 'Комментарий' }
const channelIcon  = {
  call:      <Phone size={13} />,
  whatsapp:  <MessageCircle size={13} />,
  comment:   <FileText size={13} />,
}

function formatDate(str) {
  if (!str) return '—'
  const s = str.slice(0, 10)
  const [y, m, d] = s.split('-')
  return `${d}.${m}.${y}`
}

function initials(name) {
  if (!name) return '?'
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase()
}

// ── shared UI ─────────────────────────────────────────────────────────────────

function Avatar({ name, photo, size = 56 }) {
  if (photo) return (
    <img src={photo} alt="" style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
  )
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <span style={{ color: '#fff', fontSize: size * 0.33, fontWeight: 700 }}>{initials(name)}</span>
    </div>
  )
}

function Badge({ bg, color, children }) {
  return <span style={{ padding: '3px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: bg, color }}>{children}</span>
}

function InfoRow({ label, value }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', fontFamily: 'Manrope' }}>{label}</span>
      <span style={{ fontSize: 13, color: '#1A1A2E', fontFamily: 'Manrope' }}>{value || '—'}</span>
    </div>
  )
}

// ── кастомный дропдаун (единый стиль) ────────────────────────────────────────

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
      {label && <div style={{ fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }}>{label}</div>}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 12px',
          border: `1.5px solid ${open ? '#E8998D' : active ? '#E8998D' : '#EBEBF0'}`,
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
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 200, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', overflow: 'hidden' }}>
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

// ── кастомный чекбокс ─────────────────────────────────────────────────────────

function Checkbox({ label, checked, onChange }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', userSelect: 'none' }}>
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} style={{ display: 'none' }} />
      <div style={{ width: 16, height: 16, flexShrink: 0, borderRadius: 4, border: `2px solid ${checked ? '#C97B6E' : '#D1D5DB'}`, background: checked ? '#C97B6E' : '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'all 0.15s' }}>
        {checked && <svg width="9" height="7" viewBox="0 0 10 8" fill="none"><path d="M1 4L3.8 7L9 1" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      </div>
      <span style={{ fontSize: 13, fontFamily: 'Manrope', color: checked ? '#C97B6E' : '#374151', fontWeight: checked ? 600 : 400 }}>{label}</span>
    </label>
  )
}

// ── segmented control (каналы коммуникации) ───────────────────────────────────

function SegmentedControl({ options, value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {options.map(([v, l, icon]) => (
        <button key={v} type="button" onClick={() => onChange(v)}
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 600, fontFamily: 'Manrope',
            background: value === v ? 'linear-gradient(135deg, #E8998D, #C97B6E)' : '#F0F0F5',
            color: value === v ? '#fff' : '#6B7280',
            transition: 'all 0.15s',
          }}
        >
          {icon} {l}
        </button>
      ))}
    </div>
  )
}

// ── вкладка: Основная информация ──────────────────────────────────────────────

function TabInfo({ child }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 20 }}>
      <InfoRow label="Дата рождения" value={formatDate(child.birth_date)} />
      <InfoRow label="Пол" value={genderLabel[child.gender] || '—'} />
      <InfoRow label="Направления" value={child.directions?.length ? child.directions.join(', ') : '—'} />
      <InfoRow label="Создан" value={formatDate(child.created_at?.slice(0, 10))} />
      {child.medical_notes !== undefined && (
        <div style={{ gridColumn: '1 / -1' }}>
          <InfoRow label="Медицинские заметки" value={child.medical_notes || '—'} />
        </div>
      )}
      {child.consent_given !== undefined && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, gridColumn: '1 / -1' }}>
          {child.consent_given
            ? <CheckCircle size={15} style={{ color: '#16A34A' }} />
            : <X size={15} style={{ color: '#DC2626' }} />}
          <span style={{ fontSize: 13, color: '#6B7280', fontFamily: 'Manrope' }}>
            {child.consent_given ? 'Согласие получено' : 'Согласие не получено'}
          </span>
        </div>
      )}
      {child.leave_reason && (
        <div style={{ gridColumn: '1 / -1' }}>
          <InfoRow label="Причина ухода" value={child.leave_reason} />
        </div>
      )}
    </div>
  )
}

// ── вкладка: Контакты ─────────────────────────────────────────────────────────

function TabContacts({ childId }) {
  const [contacts, setContacts] = useState([])
  const [parents, setParents]   = useState([])
  const [loading, setLoading]   = useState(true)
  const [showAdd, setShowAdd]   = useState(false)
  const [form, setForm]         = useState({ parent_contact: '', role: 'mother', is_payer: false, is_primary_contact: false })
  const [saving, setSaving]     = useState(false)
  const [errors, setErrors]     = useState({})

  useEffect(() => { load() }, [childId])

  async function load() {
    setLoading(true)
    try {
      const [cr, pr] = await Promise.all([
        axios.get(`/api/v1/clients/child-contacts/?child=${childId}`, { headers: authHeaders() }),
        axios.get('/api/v1/clients/parents/', { headers: authHeaders() }),
      ])
      setContacts(cr.data.results || cr.data)
      setParents(pr.data.results  || pr.data)
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function handleAdd(e) {
    e.preventDefault()
    setSaving(true); setErrors({})
    try {
      await axios.post('/api/v1/clients/child-contacts/', {
        child: Number(childId),
        parent_contact: Number(form.parent_contact),
        role: form.role,
        is_payer: form.is_payer,
        is_primary_contact: form.is_primary_contact,
      }, { headers: authHeaders() })
      setShowAdd(false)
      setForm({ parent_contact: '', role: 'mother', is_payer: false, is_primary_contact: false })
      load()
    } catch(err) { setErrors(err.response?.data || { non_field_errors: 'Ошибка сервера' }) }
    finally { setSaving(false) }
  }

  async function handleDetach(id) {
    if (!window.confirm('Отвязать контакт?')) return
    try { await axios.delete(`/api/v1/clients/child-contacts/${id}/`, { headers: authHeaders() }); load() }
    catch(e) { console.error(e) }
  }

  if (loading) return <p style={{ color: '#9CA3AF', fontSize: 13, padding: 16 }}>Загрузка...</p>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        <button onClick={() => setShowAdd(!showAdd)} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }}>
          <Plus size={13} /> Привязать контакт
        </button>
      </div>

      {/* Форма */}
      {showAdd && (
        <div
            style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
            onClick={() => setShowAdd(false)}
        >
            <div
            style={{ background: '#fff', borderRadius: 16, width: '100%', maxWidth: 500, padding: '24px 24px 20px' }}
            onClick={e => e.stopPropagation()}
            >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                <h2 style={{ fontSize: 16, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>Привязать контакт</h2>
                <button onClick={() => setShowAdd(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF' }}><X size={18} /></button>
            </div>
            <form onSubmit={handleAdd}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
                <CustomSelect
                    label="Родитель / контакт *"
                    value={form.parent_contact}
                    onChange={v => setForm(f => ({ ...f, parent_contact: v }))}
                    options={parents.map(p => [String(p.id), p.full_name])}
                    placeholder="Выберите контакт"
                />
                <CustomSelect
                    label="Роль *"
                    value={form.role}
                    onChange={v => setForm(f => ({ ...f, role: v }))}
                    options={Object.entries(roleLabel).map(([v, l]) => [v, l])}
                />
                </div>
                <div style={{ display: 'flex', gap: 20, marginBottom: 16 }}>
                <Checkbox label="Плательщик" checked={form.is_payer} onChange={v => setForm(f => ({ ...f, is_payer: v }))} />
                <Checkbox label="Основной контакт" checked={form.is_primary_contact} onChange={v => setForm(f => ({ ...f, is_primary_contact: v }))} />
                </div>
                {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 10 }}>{errors.non_field_errors}</p>}
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button type="button" onClick={() => setShowAdd(false)} style={{ padding: '9px 18px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>Отмена</button>
                <button type="submit" disabled={saving} style={{ padding: '9px 18px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
                    {saving ? 'Сохранение...' : 'Привязать'}
                </button>
                </div>
            </form>
            </div>
        </div>
        )}

      {contacts.length === 0 ? (
        <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 32 }}>Контакты не привязаны</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {contacts.map(c => (
            <div key={c.id} style={{ background: '#FAFAFA', border: '1px solid #F0F0F5', borderRadius: 12, padding: '14px 16px', display: 'flex', alignItems: 'center', gap: 14 }}>
              <Avatar name={c.parent_contact_full_name} size={40} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#1A1A2E', fontFamily: 'Manrope' }}>{c.parent_contact_full_name}</div>
                <div style={{ fontSize: 12, color: '#6B7280', fontFamily: 'Manrope', marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                  <span>{roleLabel[c.role] || c.role}</span>
                  {c.is_payer           && <Badge bg="#F0FDF4" color="#16A34A">Плательщик</Badge>}
                  {c.is_primary_contact && <Badge bg="#EFF6FF" color="#2563EB">Основной</Badge>}
                </div>
              </div>
              <button onClick={() => handleDetach(c.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#D1D5DB', padding: 4 }} title="Отвязать">
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const MaskedDateInput = React.forwardRef(({ onClick, placeholder, rawVal, onRawChange, onRawBlur }, ref) => (
    <div style={{ position: 'relative' }}>
      <input
        ref={ref}
        value={rawVal}
        placeholder={placeholder}
        maxLength={10}
        onChange={e => {
          let v = e.target.value.replace(/\D/g, '')
          if (v.length > 2) v = v.slice(0,2) + '.' + v.slice(2)
          if (v.length > 5) v = v.slice(0,5) + '.' + v.slice(5)
          if (v.length > 10) v = v.slice(0,10)
          onRawChange(v)
        }}
        onBlur={onRawBlur}
        onFocus={onClick}
        style={{
          padding: '7px 12px', paddingRight: 36,
          border: '1.5px solid #EBEBF0', borderRadius: 8,
          fontSize: 13, fontFamily: 'Manrope',
          outline: 'none', background: '#FAFAFA',
          width: 150, boxSizing: 'border-box',
        }}
      />
      <svg viewBox="0 0 24 24" width="15" height="15" style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', stroke: '#9CA3AF', fill: 'none', strokeWidth: 2, pointerEvents: 'none' }}>
        <rect x="3" y="4" width="18" height="18" rx="2"/>
        <line x1="16" y1="2" x2="16" y2="6"/>
        <line x1="8" y1="2" x2="8" y2="6"/>
        <line x1="3" y1="10" x2="21" y2="10"/>
      </svg>
    </div>
  ))

  function TabCommunications({ childId, contacts }) {
    const [logs, setLogs]               = useState([])
    const [loading, setLoading]         = useState(true)
    const [channel, setChannel]         = useState('call')
    const [note, setNote]               = useState('')
    const [contactId, setContactId]     = useState('')
    const [saving, setSaving]           = useState(false)
    const [dateFrom, setDateFrom]       = useState(null)
    const [dateTo, setDateTo]           = useState(null)
    const [dateFromRaw, setDateFromRaw] = useState('')
    const [dateToRaw, setDateToRaw]     = useState('')

    function toISO(date) {
      if (!date) return ''
      const d = String(date.getDate()).padStart(2,'0')
      const m = String(date.getMonth()+1).padStart(2,'0')
      const y = date.getFullYear()
      return `${y}-${m}-${d}`
    }

    function dateToStr(date) {
      return `${String(date.getDate()).padStart(2,'0')}.${String(date.getMonth()+1).padStart(2,'0')}.${date.getFullYear()}`
    }

    function parseRaw(val) {
      const parts = val.split('.')
      if (parts.length === 3 && parts[2].length === 4) {
        const d = new Date(`${parts[2]}-${parts[1]}-${parts[0]}`)
        if (!isNaN(d)) return d
      }
      return null
    }

    useEffect(() => { loadLogs() }, [childId, dateFrom, dateTo])

    async function loadLogs() {
      setLoading(true)
      try {
        const params = { child: childId }
        if (dateFrom) params.date_from = toISO(dateFrom)
        if (dateTo)   params.date_to   = toISO(dateTo)
        const res = await axios.get('/api/v1/communications/', { headers: authHeaders(), params })
        setLogs(res.data.results || res.data)
      } catch(e) { console.error(e) }
      finally { setLoading(false) }
    }

    async function handleSubmit(e) {
      e.preventDefault()
      if (!note.trim()) return
      setSaving(true)
      try {
        await axios.post('/api/v1/communications/', {
          child: Number(childId),
          channel,
          note,
          parent_contact: contactId ? Number(contactId) : null,
        }, { headers: authHeaders() })
        setNote(''); setContactId('')
        loadLogs()
      } catch(e) { console.error(e) }
      finally { setSaving(false) }
    }

    const channelOptions = [
      ['call',     'Звонок',      <Phone size={13} />],
      ['whatsapp', 'WhatsApp',    <MessageCircle size={13} />],
      ['comment',  'Комментарий', <FileText size={13} />],
    ]

    const lbl10 = {
      fontSize: 10, fontWeight: 700, color: '#9CA3AF',
      textTransform: 'uppercase', letterSpacing: '0.07em',
      marginBottom: 5, fontFamily: 'Manrope',
    }

    return (
      <div>
        {/* Форма добавления */}
        <div style={{ background: '#FAFAFA', border: '1.5px solid #EBEBF0', borderRadius: 12, padding: '18px 20px', marginBottom: 20 }}>
          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 14 }}>
              <div style={lbl10}>Канал *</div>
              <div style={{ display: 'flex', gap: 6 }}>
                {channelOptions.map(([v, l, icon]) => (
                  <button key={v} type="button" onClick={() => setChannel(v)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '7px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
                      fontSize: 13, fontWeight: 600, fontFamily: 'Manrope',
                      background: channel === v ? 'linear-gradient(135deg, #E8998D, #C97B6E)' : '#F0F0F5',
                      color: channel === v ? '#fff' : '#6B7280',
                      transition: 'all 0.15s',
                    }}
                  >{icon} {l}</button>
                ))}
              </div>
            </div>

            {contacts.length > 0 && (
              <div style={{ marginBottom: 14 }}>
                <CustomSelect
                  label="Контакт"
                  value={contactId}
                  onChange={setContactId}
                  options={[['', '—'], ...contacts.map(c => [String(c.parent_contact), c.parent_contact_full_name])]}
                  placeholder="—"
                />
              </div>
            )}

            <div style={{ marginBottom: 14 }}>
              <div style={lbl10}>Заметка *</div>
              <textarea
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="Введите заметку..."
                required
                style={{ width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', background: '#fff', minHeight: 80, resize: 'vertical', boxSizing: 'border-box' }}
              />
            </div>

            <button type="submit" disabled={saving}
              style={{ padding: '8px 18px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
              {saving ? 'Сохранение...' : 'Добавить запись'}
            </button>
          </form>
        </div>

        {/* История */}
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#1A1A2E', fontFamily: 'Manrope', marginBottom: 12 }}>История</div>

          <div style={{ display: 'flex', gap: 10, marginBottom: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div>
              <div style={lbl10}>Дата от</div>
              <DatePicker
                selected={dateFrom}
                onChange={date => {
                  setDateFrom(date)
                  setDateFromRaw(date ? dateToStr(date) : '')
                }}
                dateFormat="dd.MM.yyyy"
                placeholderText="ДД.ММ.ГГГГ"
                locale="ru"
                popperPlacement="bottom-start"
                customInput={
                  <MaskedDateInput
                    rawVal={dateFromRaw}
                    onRawChange={val => {
                      setDateFromRaw(val)
                      const parsed = parseRaw(val)
                      if (parsed) setDateFrom(parsed)
                      else if (!val) setDateFrom(null)
                    }}
                    onRawBlur={() => {
                      const parsed = parseRaw(dateFromRaw)
                      if (!parsed) { setDateFromRaw(''); setDateFrom(null) }
                    }}
                    placeholder="ДД.ММ.ГГГГ"
                  />
                }
              />
            </div>
            <div>
              <div style={lbl10}>Дата до</div>
              <DatePicker
                selected={dateTo}
                onChange={date => {
                  setDateTo(date)
                  setDateToRaw(date ? dateToStr(date) : '')
                }}
                dateFormat="dd.MM.yyyy"
                placeholderText="ДД.ММ.ГГГГ"
                locale="ru"
                popperPlacement="bottom-start"
                customInput={
                  <MaskedDateInput
                    rawVal={dateToRaw}
                    onRawChange={val => {
                      setDateToRaw(val)
                      const parsed = parseRaw(val)
                      if (parsed) setDateTo(parsed)
                      else if (!val) setDateTo(null)
                    }}
                    onRawBlur={() => {
                      const parsed = parseRaw(dateToRaw)
                      if (!parsed) { setDateToRaw(''); setDateTo(null) }
                    }}
                    placeholder="ДД.ММ.ГГГГ"
                  />
                }
              />
            </div>
            {(dateFrom || dateTo) && (
              <button
                onClick={() => { setDateFrom(null); setDateTo(null); setDateFromRaw(''); setDateToRaw('') }}
                style={{ padding: '7px 14px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 12, cursor: 'pointer', fontFamily: 'Manrope', color: '#9CA3AF', display: 'flex', alignItems: 'center', gap: 4 }}
              >
                <X size={12} /> Сбросить
              </button>
            )}
          </div>

          {loading ? (
            <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 24 }}>Загрузка...</p>
          ) : logs.length === 0 ? (
            <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 24 }}>Записей пока нет</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {logs.map(log => (
                <div key={log.id} style={{ background: '#FAFAFA', border: '1px solid #F0F0F5', borderRadius: 12, padding: '14px 16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 6, background: '#FDF0EE', color: '#C97B6E', fontSize: 12, fontWeight: 600, fontFamily: 'Manrope' }}>
                      {channelIcon[log.channel]} {channelLabel[log.channel] || log.channel}
                    </span>
                    {log.parent_contact_full_name && (
                      <span style={{ fontSize: 12, color: '#6B7280', fontFamily: 'Manrope' }}>{log.parent_contact_full_name}</span>
                    )}
                    <span style={{ marginLeft: 'auto', fontSize: 11, color: '#9CA3AF', fontFamily: 'Manrope' }}>{formatDate(log.created_at?.slice(0,10))}</span>
                  </div>
                  <p style={{ fontSize: 13, color: '#374151', fontFamily: 'Manrope', margin: 0, lineHeight: 1.5 }}>{log.note}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }
// ── main ──────────────────────────────────────────────────────────────────────

const TABS = [
  { slug: 'info',           label: 'Основная информация' },
  { slug: 'contacts',       label: 'Контакты' },
  { slug: 'communications', label: 'Коммуникации' },
]

export default function ChildDetail() {
  const { id }   = useParams()
  const navigate = useNavigate()
  const [child, setChild]       = useState(null)
  const [contacts, setContacts] = useState([])
  const [loading, setLoading]   = useState(true)
  const [activeTab, setActiveTab] = useState('info')
  const [showEdit, setShowEdit] = useState(false)

  useEffect(() => { loadChild() }, [id])

  async function loadChild() {
    setLoading(true)
    try {
      const [childRes, contactsRes] = await Promise.all([
        axios.get(`/api/v1/clients/children/${id}/`, { headers: authHeaders() }),
        axios.get(`/api/v1/clients/child-contacts/?child=${id}`, { headers: authHeaders() }),
      ])
      setChild(childRes.data)
      setContacts(contactsRes.data.results || contactsRes.data)
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }

  if (loading) return <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</div>
  if (!child)  return <div style={{ padding: 32, textAlign: 'center', color: '#DC2626', fontSize: 13 }}>Ребёнок не найден</div>

  const st = statusColors[child.status] || statusColors.active

  return (
    <div>
      {/* Back */}
      <button onClick={() => navigate('/children')}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', fontSize: 13, fontFamily: 'Manrope', marginBottom: 16, padding: 0 }}>
        <ArrowLeft size={14} /> К списку детей
      </button>

      {/* Header */}
      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 16, border: '1px solid #F0F0F5' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
          <Avatar name={child.full_name} photo={child.photo_url} size={56} />
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>{child.full_name}</h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
              {child.age && <span style={{ fontSize: 13, color: '#6B7280', fontFamily: 'Manrope' }}>{child.age} лет</span>}
              <Badge bg={st.bg} color={st.color}>{st.label}</Badge>
            </div>
          </div>
          <button onClick={() => setShowEdit(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>
            <Edit2 size={13} /> Редактировать
          </button>
        </div>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', paddingTop: 16, borderTop: '1px solid #F0F0F5' }}>
          <InfoRow label="Дата рождения" value={formatDate(child.birth_date)} />
          <InfoRow label="Пол"           value={genderLabel[child.gender] || '—'} />
          <InfoRow label="Создан"        value={formatDate(child.created_at?.slice(0, 10))} />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, background: '#fff', borderRadius: 10, padding: 4, border: '1px solid #F0F0F5', width: 'fit-content' }}>
        {TABS.map(tab => (
          <button key={tab.slug} onClick={() => setActiveTab(tab.slug)}
            style={{
              padding: '7px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: 600, fontFamily: 'Manrope',
              background: activeTab === tab.slug ? 'linear-gradient(135deg, #E8998D, #C97B6E)' : 'transparent',
              color: activeTab === tab.slug ? '#fff' : '#6B7280',
              transition: 'all 0.15s',
            }}
          >{tab.label}</button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', border: '1px solid #F0F0F5' }}>
        {activeTab === 'info'           && <TabInfo child={child} />}
        {activeTab === 'contacts'       && <TabContacts childId={id} />}
        {activeTab === 'communications' && <TabCommunications childId={id} contacts={contacts} />}
      </div>

      {showEdit && (
        <ChildModal
          child={child}
          onClose={() => setShowEdit(false)}
          onSaved={() => { setShowEdit(false); loadChild() }}
        />
      )}
    </div>
  )
}
