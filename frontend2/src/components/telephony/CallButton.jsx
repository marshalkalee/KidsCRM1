import { Phone } from 'lucide-react'
import api from '../../api/axios'
import { t } from '../../i18n'
import { cn } from '../../ui'

/** Click-to-call through the PBX with an honest tel: fallback. */
export default function CallButton({ phone, className, children, showIcon = true }) {
  async function call() {
    if (!phone) return
    try {
      const { data } = await api.post('messaging/telephony/outgoing/', { phone })
      if (!data.started && data.tel_url) window.location.href = data.tel_url
    } catch {
      window.location.href = `tel:${phone}`
    }
  }
  return (
    <button type="button" onClick={call} className={cn('inline-flex items-center justify-center gap-2', className)}>
      {showIcon && <Phone className="size-4" />}
      {children || t('Позвонить')}
    </button>
  )
}
