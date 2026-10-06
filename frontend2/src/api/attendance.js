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

export function resetAttendance({ lesson, child }) {
  return api.post('attendance/reset/', { lesson, child }).then(res => res.data)
}

export function resetAllAttendance(lessonId) {
  return api.post('attendance/reset-all/', { lesson: lessonId }).then(res => res.data)
}

export function fetchParentNotes(lessonId) {
  return api.get('attendance/parent-notes/', { params: { lesson: lessonId } }).then(res => res.data)
}

export function createParentNote({ lesson, scope, child, kind, body, validUntil }) {
  return api.post('attendance/parent-notes/', {
    lesson,
    scope,
    child: child || null,
    kind,
    body,
    valid_until: validUntil || null,
  }).then(res => res.data)
}

export function updateParentNote(noteId, { kind, body, validUntil }) {
  return api.patch(`attendance/parent-notes/${noteId}/`, {
    kind,
    body,
    valid_until: validUntil || null,
  }).then(res => res.data)
}

export function deleteParentNote(noteId) {
  return api.delete(`attendance/parent-notes/${noteId}/`)
}
