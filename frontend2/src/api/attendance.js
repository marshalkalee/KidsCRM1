import api from './axios'

export function fetchLesson(lessonId) {
  return api.get(`schedule/${lessonId}/`).then(res => res.data)
}

export function fetchAttendanceRoster(lessonId) {
  return api.get('attendance/roster/', { params: { lesson: lessonId } }).then(res => res.data)
}

export function markAttendance({ lesson, child, status, absenceReason }) {
  return api
    .post('attendance/mark/', {
      lesson,
      child,
      status,
      absence_reason: absenceReason || '',
    })
    .then(res => res.data)
}

export function markAllPresent(lessonId) {
  return api.post('attendance/mark-all-present/', { lesson: lessonId }).then(res => res.data)
}
