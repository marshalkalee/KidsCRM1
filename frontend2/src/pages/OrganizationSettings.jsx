import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { ChevronDown, Check, Save } from 'lucide-react'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

// Реальные IANA-зоны стран СНГ/Азии — та же выборка, что в старой Django-форме
// (backend/domains/platform/tenants/forms.py: TIMEZONE_CHOICES), не полный
// zoneinfo.available_timezones() — тот неюзабелен как список на ~600 записей.
const TIMEZONES = [
  'Asia/Almaty', 'Asia/Aqtobe', 'Asia/Qyzylorda', 'Asia/Bishkek', 'Asia/Tashkent',
  'Asia/Dushanbe', 'Asia/Ashgabat', 'Asia/Yekaterinburg', 'Asia/Novosibirsk',
  'Europe/Moscow', 'UTC',
]

const THRESHOLDS = [
  { key: 'subscription_ending_lessons_threshold', label: 'Абонемент заканчивается при ≤ N занятий', min: 0, max: 100, default: 3 },
  { key: 'subscription_ending_days_threshold', label: 'Абонемент заканчивается при ≤ N дней', min: 0, max: 365, default: 7 },
  { key: 'debt_overdue_days_threshold', label: 'Задолженность просрочена после N дней', min: 0, max: 365, default: 5 },
  { key: 'group_underfilled_percent_threshold', label: 'Группа недозаполнена при < X% вместимости', min: 0, max: 100, default: 50 },
]

const lbl = { fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }
const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box', background: '#fff' }
const card = { background: '#fff', borderRadius: 16, border: '1px solid #F0F0F5', padding: '20px 24px', marginBottom: 16 }

function TimezoneSelect({ value, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef()

  useEffect(() => {
    function h(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  return (
    <div ref={ref} style={{ position: 'relative', width: '100%' }}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 12px', border: `1.5px solid ${open ? '#E8998D' : '#EBEBF0'}`, borderRadius: 8,
          background: '#fff', fontSize: 13, fontFamily: 'Manrope', color: '#1A1A2E', cursor: 'pointer', outline: 'none',
        }}
      >
        {value}
        <ChevronDown size={13} style={{ color: '#9CA3AF', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 200, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', maxHeight: 260, overflowY: 'auto' }}>
          {TIMEZONES.map(tz => (
            <div key={tz} onClick={() => { onChange(tz); setOpen(false) }}
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '9px 12px', fontSize: 13, fontFamily: 'Manrope', color: tz === value ? '#C97B6E' : '#374151', background: tz === value ? '#FDF0EE' : '#fff', cursor: 'pointer' }}
              onMouseEnter={e => { if (tz !== value) e.currentTarget.style.background = '#FAFAFA' }}
              onMouseLeave={e => { if (tz !== value) e.currentTarget.style.background = '#fff' }}
            >
              {tz}
              {tz === value && <Check size={13} style={{ color: '#C97B6E' }} />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function OrganizationSettings() {
  const [loading, setLoading] = useState(true)
  const [forbidden, setForbidden] = useState(false)
  const [name, setName] = useState('')
  const [timezone, setTimezone] = useState('Asia/Almaty')
  const [thresholds, setThresholds] = useState(() => Object.fromEntries(THRESHOLDS.map(t => [t.key, t.default])))
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    axios.get('/api/v1/organization/', { headers: authHeaders() })
      .then(res => {
        const org = res.data
        setName(org.name)
        setTimezone(org.timezone)
        setThresholds(prev => {
          const next = { ...prev }
          THRESHOLDS.forEach(t => { next[t.key] = org.settings?.[t.key] ?? t.default })
          return next
        })
      })
      .catch(err => { if (err.response?.status === 403) setForbidden(true) })
      .finally(() => setLoading(false))
  }, [])

  function setThreshold(key, value) {
    setThresholds(t => ({ ...t, [key]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setSaving(true); setErrors({}); setSaved(false)
    try {
      await axios.patch('/api/v1/organization/', {
        name,
        timezone,
        settings: Object.fromEntries(THRESHOLDS.map(t => [t.key, Number(thresholds[t.key])])),
      }, { headers: authHeaders() })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setErrors(err.response?.data || { non_field_errors: 'Ошибка сервера' })
    } finally { setSaving(false) }
  }

  if (loading) return <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</div>
  if (forbidden) return (
    <div style={{ ...card, textAlign: 'center', color: '#9CA3AF', fontSize: 13, padding: 40 }}>
      Настройки организации доступны только владельцу.
    </div>
  )

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Настройки организации</h1>
        <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>Общие параметры и пороги автостатусов</p>
      </div>

      <form onSubmit={handleSubmit} style={{ maxWidth: 560 }}>
        <div style={card}>
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#1A1A2E', margin: '0 0 16px', fontFamily: 'Manrope' }}>Организация</h2>
          <div style={{ marginBottom: 14 }}>
            <div style={lbl}>Название организации</div>
            <input value={name} onChange={e => setName(e.target.value)} required style={inputStyle} />
            {errors.name && <p style={{ color: '#DC2626', fontSize: 12, margin: '4px 0 0' }}>{errors.name[0]}</p>}
          </div>
          <div>
            <div style={lbl}>Часовой пояс</div>
            <TimezoneSelect value={timezone} onChange={setTimezone} />
          </div>
        </div>

        <div style={card}>
          <h2 style={{ fontSize: 14, fontWeight: 700, color: '#1A1A2E', margin: '0 0 6px', fontFamily: 'Manrope' }}>Пороги автостатусов</h2>
          <p style={{ fontSize: 12, color: '#9CA3AF', fontFamily: 'Manrope', margin: '0 0 16px', lineHeight: 1.6 }}>
            Эти пороги использует аналитика и экраны продлений/задолженностей — меняются здесь, не в коде.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {THRESHOLDS.map(t => (
              <div key={t.key}>
                <div style={lbl}>{t.label}</div>
                <input
                  type="number" min={t.min} max={t.max}
                  value={thresholds[t.key]}
                  onChange={e => setThreshold(t.key, e.target.value)}
                  style={{ ...inputStyle, maxWidth: 140 }}
                />
              </div>
            ))}
          </div>
        </div>

        {errors.non_field_errors && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 12 }}>{errors.non_field_errors}</p>}

        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button type="submit" disabled={saving} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 20px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
            <Save size={14} /> {saving ? 'Сохранение...' : 'Сохранить'}
          </button>
          {saved && <span style={{ fontSize: 13, color: '#16A34A', fontFamily: 'Manrope' }}>Сохранено</span>}
        </div>
      </form>
    </div>
  )
}
