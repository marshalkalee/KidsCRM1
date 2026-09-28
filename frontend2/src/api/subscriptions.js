import api from './axios'

export function fetchChildSubscriptions(childId) {
  return api.get('subscriptions/', { params: { child_id: childId } }).then(r => r.data.results)
}

export function fetchLedger(subscriptionId) {
  return api.get(`subscriptions/${subscriptionId}/ledger/`).then(r => r.data)
}

export function fetchFreezes(subscriptionId) {
  return api.get(`subscriptions/${subscriptionId}/freezes/`).then(r => r.data)
}

export function freezeSubscription(subscriptionId, payload) {
  return api.post(`subscriptions/${subscriptionId}/freeze/`, payload).then(r => r.data)
}

export function unfreezeSubscription(subscriptionId, payload = {}) {
  return api.post(`subscriptions/${subscriptionId}/unfreeze/`, payload).then(r => r.data)
}

export function renewSubscription(subscriptionId, payload) {
  return api.post(`subscriptions/${subscriptionId}/renew/`, payload).then(r => r.data)
}

export function sellSubscription(payload) {
  return api.post('subscriptions/sell/', payload).then(r => r.data)
}