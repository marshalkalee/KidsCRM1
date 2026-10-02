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
// Счета на удалённую оплату Kaspi (backend: payments/remote.py).
export function fetchPaymentRequests(childId, status) {
  return api.get('payments/requests/', { params: { child_id: childId, status } }).then(r => r.data.results)
}

export function fetchPaymentRequestOptions(childId) {
  return api.get('payments/requests/options/', { params: { child_id: childId } }).then(r => r.data)
}

export function createPaymentRequest(payload) {
  return api.post('payments/requests/', payload).then(r => r.data)
}

export function confirmPaymentRequest(id) {
  return api.post(`payments/requests/${id}/confirm/`).then(r => r.data)
}

export function cancelPaymentRequest(id) {
  return api.post(`payments/requests/${id}/cancel/`).then(r => r.data)
}
