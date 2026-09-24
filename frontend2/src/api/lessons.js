import api from './axios'

export function fetchLessons(dateFrom, dateTo) {
  return api
    .get('schedule/', { params: { date_from: dateFrom, date_to: dateTo } })
    .then(res => res.data.results || res.data)
}

export function fetchGroups() {
  return api.get('groups/').then(res => res.data.results || res.data)
}

export function fetchRooms() {
  return api.get('rooms/').then(res => res.data.results || res.data)
}

export function fetchTeachers() {
  return api
    .get('users/')
    .then(res => (res.data.results || res.data).filter(u => u.role === 'teacher'))
}

export function createLesson(payload) {
  return api.post('schedule/', payload).then(res => res.data)
}

export function cancelLesson(id, reason) {
  return api.post(`schedule/${id}/cancel/`, { reason }).then(res => res.data)
}

export function rescheduleLesson(id, payload) {
  return api.post(`schedule/${id}/reschedule/`, payload).then(res => res.data)
}
