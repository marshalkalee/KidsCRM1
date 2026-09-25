import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowLeft, Edit2, Phone, MessageCircle, User } from 'lucide-react'

const statusColors = {
  active: { bg: '#F0FDF4', color: '#16A34A', label: 'Активен' },
  paused: { bg: '#FFFBEB', color: '#D97706', label: 'Заморожен' },
  left: { bg: '#F9FAFB', color: '#6B7280', label: 'Ушёл' },
}

const tabs = [
  { slug: 'contacts', label: 'Контакты' },
  { slug: 'communications', label: 'Коммуникации' },
  { slug: 'subscriptions', label: 'Абонементы' },
  { slug: 'payments', label: 'Оплаты' },
]

export default function ChildCard() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [child, setChild] = useState(null)
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('contacts')

  useEffect(() => { loadChild() }, [id])

  async function loadChild() {
    setLoading(true)
    try {
      const token = localStorage.getItem('access')
      const headers = { Authorization: `Bearer ${token}` }
      const [childRes, contactsRes] = await Promise.all([
        axios.get(`/api/v1/clients/children/${id}/`, { headers }),
        axios.get(`/api/v1/clients/children/${id}/tabs/contacts/`, { headers }),
      ])
      setChild(childRes.data)
      setContacts(contactsRes.data.results || contactsRes.data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, color: '#9CA3AF' }}>
      Загрузка...
    </div>
  )

  if (!child) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 300, color: '#9CA3AF' }}>
      Ребёнок не найден
    </div>
  )

  const st = statusColors[child.status] || statusColors.active
  const initials = child.full_name?.split(' ').map(w => w[0]).join('').slice(0, 2)

  const card = { background: '#fff', borderRadius: 12, border: '1px solid #F0F0F5' }

  return (
    <div>
      {/* Back */}
      <button
        onClick={() => navigate('/children')}
        style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', fontSize: 13, marginBottom: 20, fontFamily: 'Manrope', padding: 0 }}
      >
        <ArrowLeft size={16} />
        Назад к списку
      </button>

      {/* Header card */}
      <div style={{ ...card, padding: 24, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 56, height: 56, borderRadius: '50%',
            background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexShrink: 0, fontSize: 20, fontWeight: 700, color: '#fff',
          }}>
            {initials}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>{child.full_name}</h1>
              <span style={{ padding: '3px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: st.bg, color: st.color }}>
                {st.label}
              </span>
            </div>
            <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>
              {child.age ? `${child.age} лет` : ''} {child.birth_date ? `· ${child.birth_date}` : ''}
            </p>
          </div>
          <button style={{
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', border: '1px solid #F0F0F5',
            borderRadius: 8, background: '#fff', cursor: 'pointer',
            fontSize: 13, fontFamily: 'Manrope', color: '#6B7280',
          }}>
            <Edit2 size={14} />
            Редактировать
          </button>
        </div>

        {/* Facts */}
        <div style={{ display: 'flex', gap: 32, marginTop: 20, paddingTop: 20, borderTop: '1px solid #F0F0F5' }}>
          <div>
            <p style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 4px' }}>Филиал</p>
            <p style={{ fontSize: 13, fontWeight: 500, color: '#1A1A2E', margin: 0 }}>{child.branch_name || '—'}</p>
          </div>
          <div>
            <p style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 4px' }}>Направление</p>
            <p style={{ fontSize: 13, fontWeight: 500, color: '#1A1A2E', margin: 0 }}>{child.direction_names || '—'}</p>
          </div>
          <div>
            <p style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 4px' }}>Группа</p>
            <p style={{ fontSize: 13, fontWeight: 500, color: '#1A1A2E', margin: 0 }}>{child.group_name || '—'}</p>
          </div>
          {child.medical_notes && (
            <div>
              <p style={{ fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '0 0 4px' }}>Мед. заметки</p>
              <p style={{ fontSize: 13, fontWeight: 500, color: '#DC2626', margin: 0 }}>{child.medical_notes}</p>
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 16 }}>
        {tabs.map(tab => (
          <button
            key={tab.slug}
            onClick={() => setActiveTab(tab.slug)}
            style={{
              padding: '8px 16px', border: 'none', borderRadius: 8, cursor: 'pointer',
              fontSize: 13, fontWeight: activeTab === tab.slug ? 600 : 400,
              fontFamily: 'Manrope',
              background: activeTab === tab.slug ? '#FDF0EE' : 'transparent',
              color: activeTab === tab.slug ? '#C97B6E' : '#6B7280',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'contacts' && (
        <div style={card}>
          <div style={{ padding: '16px 20px', borderBottom: '1px solid #F0F0F5', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: 14, fontWeight: 600, color: '#1A1A2E', margin: 0 }}>Контакты</h3>
            <button style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '7px 14px', border: 'none', borderRadius: 8,
              background: 'linear-gradient(135deg, #E8998D, #C97B6E)',
              color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope',
            }}>
              + Добавить контакт
            </button>
          </div>
          {contacts.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Контактов пока нет</div>
          ) : contacts.map(contact => (
            <div key={contact.id} style={{ padding: '14px 20px', borderBottom: '1px solid #F0F0F5', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                background: '#F0F0F5',
                display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              }}>
                <User size={16} style={{ color: '#9CA3AF' }} />
              </div>
              <div style={{ flex: 1 }}>
                <p style={{ fontSize: 13, fontWeight: 600, color: '#1A1A2E', margin: 0 }}>{contact.full_name}</p>
                <p style={{ fontSize: 12, color: '#9CA3AF', margin: '2px 0 0' }}>{contact.role_display || contact.role}</p>
              </div>
              {contact.phone && (
                <a href={`tel:${contact.phone}`} style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#C97B6E', fontSize: 13, textDecoration: 'none' }}>
                  <Phone size={14} />
                  {contact.phone}
                </a>
              )}
              {contact.whatsapp && (
                <a href={`https://wa.me/${contact.whatsapp}`} target="_blank" rel="noreferrer" style={{ color: '#25D366', display: 'flex' }}>
                  <MessageCircle size={16} />
                </a>
              )}
            </div>
          ))}
        </div>
      )}

      {activeTab === 'communications' && (
        <div style={{ ...card, padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
          История коммуникаций — в разработке
        </div>
      )}

      {activeTab === 'subscriptions' && (
        <div style={{ ...card, padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
          Абонементы — в разработке
        </div>
      )}

      {activeTab === 'payments' && (
        <div style={{ ...card, padding: 24, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>
          Оплаты — в разработке
        </div>
      )}
    </div>
  )
}
