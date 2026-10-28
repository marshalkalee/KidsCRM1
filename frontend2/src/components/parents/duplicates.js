import api from '../../api/axios'

/**
 * Родители центра, у которых уже есть любой из номеров (кроме excludeId) —
 * предупредить о дубле перед сохранением. Общий номер у семьи бывает,
 * поэтому это предупреждение, а не запрет.
 */
export async function findParentsByPhones(numbers, excludeId) {
  const unique = [...new Set(numbers.filter(Boolean))]
  const lists = await Promise.all(
    unique.map(phone => api.get('clients/parents/', { params: { phone } })
      .then(r => r.data.results || r.data)
      .catch(() => [])),
  )
  const byId = new Map()
  lists.flat().forEach(p => { if (String(p.id) !== String(excludeId)) byId.set(p.id, p) })
  return [...byId.values()]
}
