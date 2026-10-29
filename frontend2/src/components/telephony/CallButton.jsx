import { Phone } from 'lucide-react'
import api from '../../api/axios'
import { t } from '../../i18n'
import { useSession } from '../../session/SessionContext'
import { cn } from '../../ui'

/** Click-to-call through the PBX. Without a connected PBX there is no button:
 * a tel: link does nothing on a desktop. */
export default function CallButton({ phone, className, children, showIcon = true, iconOnly = false }) {
  const { user } = useSession()
  if (!user?.can_call || !phone) return null
  async function call() {
    try {
      const { data } = await api.post('messaging/telephony/outgoing/', { phone })
      if (!data.started && data.tel_url) window.location.href = data.tel_url
    } catch {
      window.location.href = `tel:${phone}`
    }
  }
  return (
    <button
      type="button"
      onClick={call}
      title={iconOnly ? t('Позвонить') : undefined}
      aria-label={iconOnly ? t('Позвонить') : undefined}
      className={cn('inline-flex items-center justify-center gap-2', className)}
    >
      {showIcon && <Phone className="size-4" />}
      {!iconOnly && (children || t('Позвонить'))}
    </button>
  )
}
