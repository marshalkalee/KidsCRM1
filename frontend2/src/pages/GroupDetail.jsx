import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowLeft, Edit2, Plus, Trash2, Users, MapPin } from 'lucide-react'
import GroupModal from '../components/GroupModal'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

const STATUS_STYLE = {
  active: { bg: '#F0FDF4', color: '#16A34A', label: 'Активна' },
  paused: { bg: '#FFFBEB', color: '#D97706', label: 'Приостановлена' },
  closed: { bg: '#F9FAFB', color: '#6B7280', label: 'Закрыта' },
}

function formatDate(str) {
  if (!str) return '—'
  const [y, m, d] = str.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
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

// ── вкладка: Состав ──────────────────────────────────────────────────────────

function AddMemberForm({ groupId, onAdded, onCancel }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [selectedChild, setSelectedChild] = useState(null)
  const [joinedAt, setJoinedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const debounceRef = useRef()

  useEffect(() => {
    if (selectedChild || !query.trim()) { setResults([]); return }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      axios.get('/api/v1/clients/children/', { headers: authHeaders(), params: { search: query } })
        .then(res => setResults((res.data.results || res.data).slice(0, 8)))
        .catch(console.error)
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query, selectedChild])

  async function handleSubmit(e) {
    e.preventDefault()
    if (!selectedChild) { setError('Выберите ребёнка из списка'); return }
    setSaving(true); setError('')
    try {
      await axios.post(`/api/v1/groups/${groupId}/add_member/`, {
        child: selectedChild.id,
        joined_at: joinedAt,
      }, { headers: authHeaders() })
      onAdded()
    } catch (err) {
      setError(err.response?.data?.detail || err.response?.data?.non_field_errors?.[0] || 'Не удалось добавить ребёнка')
    } finally { setSaving(false) }
  }

  const inputStyle = { width: '100%', padding: '9px 12px', border: '1.5px solid #EBEBF0', borderRadius: 8, fontSize: 13, fontFamily: 'Manrope', outline: 'none', boxSizing: 'border-box' }

  return (
    <div style={{ background: '#FAFAFA', border: '1.5px solid #EBEBF0', borderRadius: 12, padding: '16px 18px', marginBottom: 16 }}>
      <form onSubmit={handleSubmit}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 200, position: 'relative' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }}>Ребёнок *</div>
            <input
              value={selectedChild ? selectedChild.full_name : query}
              onChange={e => { setSelectedChild(null); setQuery(e.target.value) }}
              placeholder="Начните вводить имя..."
              style={{ ...inputStyle, background: selectedChild ? '#FDF0EE' : '#fff', color: selectedChild ? '#C97B6E' : '#1A1A2E', fontWeight: selectedChild ? 600 : 400 }}
            />
            {results.length > 0 && !selectedChild && (
              <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 100, background: '#fff', border: '1.5px solid #F0F0F5', borderRadius: 10, boxShadow: '0 8px 24px rgba(0,0,0,0.10)', overflow: 'hidden' }}>
                {results.map(c => (
                  <div key={c.id} onClick={() => { setSelectedChild(c); setResults([]) }}
                    style={{ padding: '9px 12px', fontSize: 13, fontFamily: 'Manrope', cursor: 'pointer' }}
                    onMouseEnter={e => e.currentTarget.style.background = '#FAFAFA'}
                    onMouseLeave={e => e.currentTarget.style.background = '#fff'}
                  >
                    {c.full_name} {c.age ? <span style={{ color: '#9CA3AF' }}>· {c.age} лет</span> : null}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div style={{ width: 160 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 5, fontFamily: 'Manrope' }}>Дата вступления</div>
            <input type="date" value={joinedAt} onChange={e => setJoinedAt(e.target.value)} style={inputStyle} />
          </div>
        </div>
        {error && <p style={{ color: '#DC2626', fontSize: 12, marginBottom: 10 }}>{error}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCancel} style={{ padding: '8px 16px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 12, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>Отмена</button>
          <button type="submit" disabled={saving} style={{ padding: '8px 16px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', opacity: saving ? 0.7 : 1 }}>
            {saving ? 'Добавление...' : 'Добавить'}
          </button>
        </div>
      </form>
    </div>
  )
}

function TabMembers({ groupId, full }) {
  const [members, setMembers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    axios.get(`/api/v1/groups/${groupId}/members/`, { headers: authHeaders() })
      .then(res => setMembers(res.data.results || res.data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [groupId])

  useEffect(() => { load() }, [load])

  async function handleRemove(childId, childName) {
    if (!window.confirm(`Убрать «${childName}» из группы?`)) return
    try {
      await axios.post(`/api/v1/groups/${groupId}/remove_member/`, {
        child_id: childId,
        left_at: new Date().toISOString().slice(0, 10),
      }, { headers: authHeaders() })
      load()
    } catch (e) { console.error(e) }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
        {!showAdd && (
          <button
            onClick={() => setShowAdd(true)}
            disabled={full}
            title={full ? 'Группа заполнена — сначала увеличьте вместимость или освободите место' : undefined}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: full ? '#F0F0F5' : 'linear-gradient(135deg, #E8998D, #C97B6E)', color: full ? '#9CA3AF' : '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: full ? 'default' : 'pointer', fontFamily: 'Manrope' }}
          >
            <Plus size={13} /> Добавить ребёнка
          </button>
        )}
      </div>

      {showAdd && (
        <AddMemberForm groupId={groupId} onAdded={() => { setShowAdd(false); load() }} onCancel={() => setShowAdd(false)} />
      )}

      {loading ? (
        <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 32 }}>Загрузка...</p>
      ) : members.length === 0 ? (
        <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 32 }}>В группе пока никого нет</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {members.map(m => (
            <div key={m.id} style={{ background: '#FAFAFA', border: '1px solid #F0F0F5', borderRadius: 10, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ width: 34, height: 34, borderRadius: '50%', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <span style={{ color: '#fff', fontSize: 12, fontWeight: 700 }}>{m.child_name?.charAt(0)}</span>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', fontFamily: 'Manrope' }}>{m.child_name}</div>
                <div style={{ fontSize: 11, color: '#9CA3AF', fontFamily: 'Manrope', marginTop: 2 }}>с {formatDate(m.joined_at)}</div>
              </div>
              <button onClick={() => handleRemove(m.child, m.child_name)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#D1D5DB', padding: 4 }} title="Убрать из группы">
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── вкладка: История ─────────────────────────────────────────────────────────

function TabHistory({ groupId }) {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    axios.get(`/api/v1/groups/${groupId}/history/`, { headers: authHeaders() })
      .then(res => setHistory(res.data.results || res.data))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [groupId])

  if (loading) return <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 32 }}>Загрузка...</p>
  if (history.length === 0) return <p style={{ color: '#9CA3AF', fontSize: 13, textAlign: 'center', padding: 32 }}>Истории пока нет</p>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {history.map(m => {
        const active = !m.left_at
        return (
          <div key={m.id} style={{ background: '#FAFAFA', border: '1px solid #F0F0F5', borderRadius: 10, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', fontFamily: 'Manrope' }}>{m.child_name}</div>
              <div style={{ fontSize: 11, color: '#9CA3AF', fontFamily: 'Manrope', marginTop: 2 }}>
                {formatDate(m.joined_at)} — {m.left_at ? formatDate(m.left_at) : 'по настоящее время'}
              </div>
            </div>
            <Badge bg={active ? '#F0FDF4' : '#F9FAFB'} color={active ? '#16A34A' : '#6B7280'}>{active ? 'В группе' : 'Вышел'}</Badge>
          </div>
        )
      })}
    </div>
  )
}

// ── main ──────────────────────────────────────────────────────────────────────

const TABS = [
  { slug: 'members', label: 'Состав' },
  { slug: 'history', label: 'История' },
]

export default function GroupDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [group, setGroup] = useState(null)
  const [branches, setBranches] = useState([])
  const [directions, setDirections] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('members')
  const [showEdit, setShowEdit] = useState(false)

  const loadGroup = useCallback(() => {
    setLoading(true)
    Promise.all([
      axios.get(`/api/v1/groups/${id}/`, { headers: authHeaders() }),
      axios.get('/api/v1/branches/', { headers: authHeaders() }),
      axios.get('/api/v1/directions/', { headers: authHeaders() }),
    ]).then(([g, b, d]) => {
      setGroup(g.data)
      setBranches(b.data.results || b.data)
      setDirections(d.data.results || d.data)
    }).catch(console.error)
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => { loadGroup() }, [loadGroup])

  if (loading) return <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</div>
  if (!group) return <div style={{ padding: 32, textAlign: 'center', color: '#DC2626', fontSize: 13 }}>Группа не найдена</div>

  const st = STATUS_STYLE[group.status] || STATUS_STYLE.active
  const branch = branches.find(b => String(b.id) === String(group.branch))
  const direction = directions.find(d => String(d.id) === String(group.direction))
  const full = group.members_count >= group.capacity

  return (
    <div>
      <button onClick={() => navigate('/groups')}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', fontSize: 13, fontFamily: 'Manrope', marginBottom: 16, padding: 0 }}>
        <ArrowLeft size={14} /> К списку групп
      </button>

      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 16, border: '1px solid #F0F0F5' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 16 }}>
          <div style={{ width: 48, height: 48, borderRadius: 12, background: 'linear-gradient(135deg, #E8998D, #C97B6E)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Users size={20} style={{ color: '#fff' }} />
          </div>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: '#1A1A2E', margin: 0, fontFamily: 'Manrope' }}>{group.name}</h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
              <Badge bg={st.bg} color={st.color}>{st.label}</Badge>
              <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: full ? '#D97706' : '#6B7280', fontFamily: 'Manrope', fontWeight: full ? 600 : 400 }}>
                <Users size={13} /> {group.members_count} / {group.capacity} {full && '(заполнена)'}
              </span>
              {branch && (
                <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: '#6B7280', fontFamily: 'Manrope' }}>
                  <MapPin size={13} /> {branch.name}
                </span>
              )}
            </div>
          </div>
          <button onClick={() => setShowEdit(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', border: '1.5px solid #EBEBF0', borderRadius: 8, background: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope', color: '#6B7280' }}>
            <Edit2 size={13} /> Редактировать
          </button>
        </div>
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', paddingTop: 16, borderTop: '1px solid #F0F0F5' }}>
          <InfoRow label="Направление" value={direction?.name} />
          <InfoRow label="Возраст" value={group.age_min || group.age_max ? `${group.age_min ?? '—'}–${group.age_max ?? '—'} лет` : null} />
          <InfoRow label="Преподаватели" value={group.teachers_count ? `${group.teachers_count}` : 'не назначены'} />
        </div>
      </div>

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

      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', border: '1px solid #F0F0F5' }}>
        {activeTab === 'members' && <TabMembers groupId={id} full={full} />}
        {activeTab === 'history' && <TabHistory groupId={id} />}
      </div>

      {showEdit && (
        <GroupModal
          group={group}
          onClose={() => setShowEdit(false)}
          onSaved={() => { setShowEdit(false); loadGroup() }}
        />
      )}
    </div>
  )
}
