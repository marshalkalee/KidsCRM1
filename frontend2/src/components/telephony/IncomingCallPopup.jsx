import { useCallback, useEffect, useState } from 'react'
import { PhoneIncoming, UserPlus, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import api from '../../api/axios'
import { t } from '../../i18n'
import { Button, Card, apiErrorMessage, useToast } from '../../ui'
import { useSession } from '../../session/SessionContext'

function targetUrl(target) {
  if (!target) return ''
  if (target.type === 'child') return `/children/${target.id}`
  if (target.type === 'parent') return `/parents/${target.id}`
  if (target.type === 'lead') return `/leads/${target.id}`
  return ''
}

export default function IncomingCallPopup() {
  const { can } = useSession()
  const navigate = useNavigate()
  const toast = useToast()
  const [call, setCall] = useState(null)
  const load = useCallback(() => {
    if (!can('can_use_telephony')) return
    api.get('messaging/telephony/calls/', { params: { ringing: 1, unseen: 1 } })
      .then(response => setCall(response.data[0] || null))
      .catch(() => {})
  }, [can])
  useEffect(() => {
    load()
    const timer = window.setInterval(load, 8000)
    return () => window.clearInterval(timer)
  }, [load])

  async function dismiss() {
    await api.post(`messaging/telephony/calls/${call.id}/seen/`).catch(() => {})
    setCall(null)
  }
  async function openCard() {
    const url = targetUrl(call.target)
    await dismiss()
    if (url) navigate(url)
  }
  async function promote() {
    try {
      const { data } = await api.post(`messaging/telephony/calls/${call.id}/promote/`)
      await dismiss()
      navigate(`/leads/${data.lead_id}`)
    } catch (error) { toast.error(apiErrorMessage(error)) }
  }
  if (!call) return null
  return (
    <Card className="fixed bottom-4 right-4 z-50 w-[calc(100%-2rem)] max-w-sm border-brand-200 shadow-pop">
      <button type="button" onClick={dismiss} className="absolute right-3 top-3 text-ink-subtle" aria-label={t('Закрыть')}><X className="size-4" /></button>
      <div className="flex items-start gap-3 pr-6">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-600"><PhoneIncoming className="size-5" /></span>
        <div><p className="font-bold text-ink">{t('Входящий звонок')}</p><p className="text-sm text-ink-muted">{call.target?.name || t('Неизвестный номер')}</p><p className="text-sm font-semibold text-ink">{call.phone}</p></div>
      </div>
      <div className="mt-4 flex gap-2">
        {call.target ? <Button variant="primary" className="flex-1" onClick={openCard}>{t('Открыть карточку')}</Button> : <Button variant="primary" icon={UserPlus} className="flex-1" onClick={promote}>{t('Создать заявку')}</Button>}
        <Button onClick={dismiss}>{t('Закрыть')}</Button>
      </div>
    </Card>
  )
}
