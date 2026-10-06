import api from './axios'

export function fetchChildPayments(childId) {
  return api.get('payments/', { params: { child_id: childId } }).then(r => r.data.results)
}

export function fetchChildDebt(childId) {
  return api.get('payments/child_debt/', { params: { child_id: childId } }).then(r => r.data.debt)
}

export function recordPayment(payload) {
  return api.post('payments/', payload).then(r => r.data)
}

export function cancelPayment(paymentId, reason) {
  return api.post(`payments/${paymentId}/cancel/`, { reason }).then(r => r.data)
}
