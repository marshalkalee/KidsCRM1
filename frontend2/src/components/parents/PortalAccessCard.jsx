import { useCallback, useEffect, useState } from 'react'
import { Copy, KeyRound, MessageCircle } from 'lucide-react'
import api from '../../api/axios'
import { Badge, Button, Card, CardHeader, Modal, Skeleton, apiErrorMessage, formatDateTime, formatPhone, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'

/**
 * Доступ родителя в кабинет (Д40): вход по телефону и паролю. Пароль
 * выдаёт администратор — система генерирует его и показывает один раз;
 * передать можно в WhatsApp готовым сообщением. Новый пароль закрывает
 * прежние входы родителя.
 */
export default function PortalAccessCard({ parentId }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [data, setData] = useState(null)
  const [issued, setIssued] = useState(null)
  const [busy, setBusy] = useState(false)
  const url = `clients/parents/${parentId}/portal-access/`

  const load = useCallback(() => api.get(url).then(res => setData(res.data)).catch(err => setData({ error: apiErrorMessage(err) })), [url])
  useEffect(() => { load() }, [load])

  async function issue() {
    if (data?.has_password) {
      const ok = await confirm({
        title: t('Выдать новый пароль?'),
        message: t('Старый пароль перестанет работать, родитель выйдет на всех устройствах.'),
        confirmText: t('Выдать новый'),
      })
      if (!ok) return
    }
    setBusy(true)
    try {
      const res = await api.post(url)
      setIssued(res.data)
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <Skeleton className="h-36" />

  return (
    <Card>
      <CardHeader
        title={t('Доступ в кабинет')}
        actions={data.has_password ? <Badge tone="success">{t('Пароль выдан')}</Badge> : <Badge>{t('Нет пароля')}</Badge>}
      />
      {data.error ? (
        <p className="text-[13px] text-ink-muted">{data.error}</p>
      ) : (
        <>
          <p className="text-[13px] text-ink-muted">
            {t('Логин — номер {phone}.', { phone: formatPhone(data.phone) })}{' '}
            {data.last_login_at
              ? t('Последний вход: {when}.', { when: formatDateTime(data.last_login_at) })
              : data.has_password ? t('Ещё не заходил.') : t('Выдайте пароль, чтобы родитель мог войти.')}
          </p>
          <Button className="mt-3" icon={KeyRound} loading={busy} onClick={issue}>
            {data.has_password ? t('Выдать новый пароль') : t('Выдать пароль')}
          </Button>
        </>
      )}
      {issued && <IssuedModal issued={issued} onClose={() => setIssued(null)} />}
    </Card>
  )
}

function IssuedModal({ issued, onClose }) {
  const toast = useToast()
  async function copy(text, done) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(done)
    } catch {
      toast.error(t('Не удалось скопировать — выделите и скопируйте вручную'))
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={t('Пароль для кабинета')}
      description={t('Показывается один раз. Передайте его родителю — он сможет сменить пароль в профиле.')}
      footer={<Button variant="primary" onClick={onClose}>{t('Готово')}</Button>}
    >
      <div className="space-y-3">
        <div className="rounded-lg border border-line bg-surface-muted p-3">
          <p className="text-[12px] text-ink-muted">{t('Логин')}</p>
          <p className="font-semibold text-ink">{formatPhone(issued.phone)}</p>
          <p className="mt-2 text-[12px] text-ink-muted">{t('Пароль')}</p>
          <p className="font-mono text-lg font-bold tracking-wider text-ink">{issued.password}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={issued.whatsapp_url} target="_blank" rel="noreferrer" className="inline-flex h-9 items-center gap-2 rounded-md bg-success-50 px-3 text-[13px] font-semibold text-success-600">
            <MessageCircle className="size-4" />{t('Отправить в WhatsApp')}
          </a>
          <Button size="sm" icon={Copy} onClick={() => copy(issued.message, t('Сообщение скопировано'))}>{t('Скопировать сообщение')}</Button>
        </div>
      </div>
    </Modal>
  )
}
