import api from './axios'

export function fetchLessons(dateFrom, dateTo, filters = {}) {
  const params = { date_from: dateFrom, date_to: dateTo }
  if (filters.branch) params.branch = filters.branch
  if (filters.room) params.room = filters.room
  if (filters.teacher) params.teacher = filters.teacher
  if (filters.direction) params.direction = filters.direction
  return api.get('schedule/', { params }).then(res => res.data.results || res.data)
}

export function fetchGroups() {
  return api.get('groups/').then(res => res.data.results || res.data)
}

export function fetchRooms() {
  return api.get('rooms/').then(res => res.data.results || res.data)
}

export function fetchBranches() {
  return api.get('branches/').then(res => res.data.results || res.data)
}

export function fetchDirections() {
  return api.get('directions/').then(res => res.data.results || res.data)
}

export function fetchTeachers() {
  return api
    .get('users/')
    .then(res => (res.data.results || res.data).filter(u => u.role === 'teacher'))
}

export function fetchMe() {
  return api.get('users/auth/me/').then(res => res.data)
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
