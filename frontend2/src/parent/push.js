/*
 * Push в кабинете родителя (TRU-172). Подписка живёт в браузере (Push API
 * через сервис-воркер /parent/sw.js), сервер хранит её на аккаунт родителя.
 *
 * iPhone: Web Push в Safari работает только у кабинета, установленного на
 * экран «Домой» (iOS 16.4+), и только по HTTPS. В обычной вкладке Safari
 * подписаться нельзя — экран объясняет, что сделать.
 */
import portal from './api'

const DISMISS_KEY = 'kc-parent-push-dismissed'
const DISMISS_DAYS = 30

export function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

export function isStandalone() {
  return window.matchMedia?.('(display-mode: standalone)').matches || window.navigator.standalone === true
}

/** 'ok' | 'ios-install' (iPhone, не установлен) | 'unsupported' | 'insecure' */
export function pushSupport() {
  if (!window.isSecureContext) return 'insecure'
  if (isIOS() && !isStandalone()) return 'ios-install'
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return 'unsupported'
  return 'ok'
}

export function permission() {
  return 'Notification' in window ? Notification.permission : 'default'
}

async function registration() {
  return navigator.serviceWorker.getRegistration('/parent/') || navigator.serviceWorker.ready
}

export async function currentSubscription() {
  if (pushSupport() !== 'ok') return null
  try {
    const reg = await registration()
    return reg ? await reg.pushManager.getSubscription() : null
  } catch {
    return null
  }
}

function urlBase64ToUint8Array(value) {
  const padding = '='.repeat((4 - (value.length % 4)) % 4)
  const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)))
}

/** Спросить разрешение и подписать это устройство. Бросает Error с текстом. */
export async function enablePush(publicKey) {
  const result = await Notification.requestPermission()
  if (result !== 'granted') throw new Error('denied')
  const reg = await registration()
  const subscription = (await reg.pushManager.getSubscription())
    || await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(publicKey) })
  const { data } = await portal.post('push/', subscription.toJSON())
  return data
}

/** Отписать это устройство — при выходе и по кнопке в профиле. */
export async function disablePush() {
  const subscription = await currentSubscription()
  if (!subscription) return null
  const endpoint = subscription.endpoint
  await subscription.unsubscribe().catch(() => {})
  const { data } = await portal.delete('push/', { data: { endpoint } }).catch(() => ({ data: null }))
  return data
}

export function wasDismissed() {
  try {
    const at = Number(localStorage.getItem(DISMISS_KEY) || 0)
    return Date.now() - at < DISMISS_DAYS * 24 * 3600 * 1000
  } catch {
    return false
  }
}

export function dismiss() {
  try { localStorage.setItem(DISMISS_KEY, String(Date.now())) } catch { /* не запомнится — покажем снова */ }
}
