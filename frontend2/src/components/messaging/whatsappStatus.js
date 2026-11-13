import { useEffect, useState } from 'react'
import api from '../../api/axios'

/* Подключён ли у центра номер по QR-коду и можно ли этому сотруднику писать с него
 * (WhatsAppButton). Один запрос на страницу, общий для всех кнопок. */

let statusPromise = null

function loadStatus() {
  if (!statusPromise) {
    statusPromise = api
      .get('messaging/whatsapp/status/')
      .then(response => response.data)
      .catch(() => {
        statusPromise = null
        return { connected: false, can_send: false }
      })
  }
  return statusPromise
}

/** После подключения или отключения номера — перечитать статус. */
export function resetWhatsAppStatus() {
  statusPromise = null
}

export function useCenterWhatsApp() {
  const [status, setStatus] = useState(null)
  useEffect(() => {
    let alive = true
    loadStatus().then(value => { if (alive) setStatus(value) })
    return () => { alive = false }
  }, [])
  return status
}

export function waMeUrl(phone, text = '') {
  const digits = (phone || '').replace(/\D/g, '')
  return text ? `https://wa.me/${digits}?text=${encodeURIComponent(text)}` : `https://wa.me/${digits}`
}
