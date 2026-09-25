import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { Plus, Edit2, Archive, ArchiveRestore, DoorOpen } from 'lucide-react'
import BranchModal from '../components/BranchModal'

function authHeaders() {
  return { Authorization: `Bearer ${localStorage.getItem('access')}` }
}

export default function Branches() {
  const [branches, setBranches] = useState([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editBranch, setEditBranch] = useState(null)
  const navigate = useNavigate()

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    try {
      const res = await axios.get('/api/v1/branches/', { headers: authHeaders() })
      const list = res.data.results || res.data
      list.sort((a, b) => Number(b.is_active) - Number(a.is_active) || a.name.localeCompare(b.name))
      setBranches(list)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function toggleActive(branch) {
    try {
      await axios.patch(`/api/v1/branches/${branch.id}/`, { is_active: !branch.is_active }, { headers: authHeaders() })
      load()
    } catch (e) { console.error(e) }
  }

  const card = { background: '#fff', borderRadius: 12, border: '1px solid #F0F0F5', overflow: 'hidden' }

  return (
    <div>
      <div style={{ background: '#fff', borderRadius: 16, padding: '20px 24px', marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid #F0F0F5' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1A1A2E', margin: 0 }}>Филиалы</h1>
          <p style={{ fontSize: 13, color: '#9CA3AF', margin: '4px 0 0' }}>{branches.length} филиалов</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: 'linear-gradient(135deg, #E8998D, #C97B6E)', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'Manrope' }}
        >
          <Plus size={14} /> Новый филиал
        </button>
      </div>

      <div style={card}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #F0F0F5' }}>
              {['Название', 'Адрес', 'Телефон', 'Статус', ''].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Загрузка...</td></tr>
            ) : branches.length === 0 ? (
              <tr><td colSpan={5} style={{ padding: 32, textAlign: 'center', color: '#9CA3AF', fontSize: 13 }}>Филиалов пока нет</td></tr>
            ) : branches.map(branch => (
              <tr key={branch.id} style={{ borderBottom: '1px solid #F0F0F5', opacity: branch.is_active ? 1 : 0.55 }}>
                <td style={{ padding: '14px 16px', fontSize: 13, fontWeight: 600, color: '#1A1A2E' }}>{branch.name}</td>
                <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{branch.address || '—'}</td>
                <td style={{ padding: '14px 16px', fontSize: 13, color: '#6B7280' }}>{branch.phone || '—'}</td>
                <td style={{ padding: '14px 16px' }}>
                  <span style={{ padding: '4px 10px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: branch.is_active ? '#F0FDF4' : '#F9FAFB', color: branch.is_active ? '#16A34A' : '#6B7280' }}>
                    {branch.is_active ? 'Активен' : 'В архиве'}
                  </span>
                </td>
                <td style={{ padding: '14px 16px' }}>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                    <button
                      onClick={() => navigate(`/branches/${branch.id}/rooms`)}
                      title="Залы"
                      style={iconBtnStyle}
                    ><DoorOpen size={14} /></button>
                    <button onClick={() => setEditBranch(branch)} title="Редактировать" style={iconBtnStyle}><Edit2 size={14} /></button>
                    <button
                      onClick={() => toggleActive(branch)}
                      title={branch.is_active ? 'Архивировать' : 'Восстановить'}
                      style={iconBtnStyle}
                    >
                      {branch.is_active ? <Archive size={14} /> : <ArchiveRestore size={14} />}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {(showModal || editBranch) && (
        <BranchModal
          branch={editBranch}
          onClose={() => { setShowModal(false); setEditBranch(null) }}
          onSaved={() => { setShowModal(false); setEditBranch(null); load() }}
        />
      )}
    </div>
  )
}

const iconBtnStyle = {
  width: 30, height: 30, display: 'flex', alignItems: 'center', justifyContent: 'center',
  border: '1px solid #F0F0F5', borderRadius: 8, background: '#fff', cursor: 'pointer', color: '#6B7280',
}
