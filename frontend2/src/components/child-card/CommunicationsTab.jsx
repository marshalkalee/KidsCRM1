import { useEffect, useState } from 'react'
import api from '../../api/axios'
import { Communications } from '../communications/Communications'

/** Вкладка «Коммуникации» карточки ребёнка — общая лента по этому ребёнку. */
export default function CommunicationsTab({ child, permissions, onCountChange }) {
  const [contacts, setContacts] = useState([])
  const canCreate = permissions.can_log_communications

  useEffect(() => {
    if (!canCreate) return
    api.get('clients/child-contacts/', { params: { child: child.id } })
      .then(r => setContacts((r.data.results || r.data).map(link => ({ id: link.parent_contact, full_name: link.parent_contact_full_name }))))
      .catch(() => {})
  }, [child.id, canCreate])

  return (
    <Communications
      params={{ child: child.id }}
      canCreate={canCreate}
      childOptions={[{ id: child.id, full_name: child.full_name }]}
      contactOptions={contacts}
      onCountChange={onCountChange}
    />
  )
}
