import { useCallback, useEffect, useState } from 'react'
import { BookOpen, Copy, KeyRound, Plus, ShieldOff } from 'lucide-react'
import api from '../api/axios'
import {
  Badge, Button, Card, CardHeader, Checkbox, EmptyState, ErrorState, Field, Input, Modal, PageHeader,
  Skeleton, apiErrorMessage, cn, formatDateTime, useConfirm, useToast,
} from '../ui'
import { t } from '../i18n'

/*
 * Ключи публичного API (TRU-176, docs/public-api.md) — только владелец.
 * Ключ показывается один раз; у нас хранится хеш. Область и филиалы
 * ограничивают ключ; отзыв действует сразу.
 */
export default function ApiKeys() {
  const toast = useToast()
  const confirm = useConfirm()
  const [data, setData] = useState(null)
  const [log, setLog] = useState([])
  const [error, setError] = useState(false)
  const [creating, setCreating] = useState(false)
  const [issued, setIssued] = useState(null)

  const load = useCallback(() => {
    api.get('api-keys/').then(res => { setData(res.data); setError(false) }).catch(() => setError(true))
    api.get('api-keys/log/').then(res => setLog(res.data)).catch(() => setLog([]))
  }, [])
  useEffect(() => { load() }, [load])

  async function revoke(key) {
    const ok = await confirm({
      title: t('Отозвать ключ «{name}»?', { name: key.name }),
      message: t('Интеграции с этим ключом сразу перестанут работать. Вернуть ключ нельзя — только выпустить новый.'),
      confirmText: t('Отозвать'),
      danger: true,
    })
    if (!ok) return
    try {
      await api.post(`api-keys/${key.id}/revoke/`)
      toast.success(t('Ключ отозван'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!data) return <Skeleton className="h-96" />
  const active = data.keys.filter(k => !k.revoked_at)
  const revoked = data.keys.filter(k => k.revoked_at)

  return (
    <div>
      <PageHeader
        back={{ to: '/settings/organization', label: t('Организация') }}
        title={t('API-ключи')}
        description={t('Доступ к данным центра для своих программ: сайт, 1С, отчёты. Ключ видит только выбранные филиалы и не видит контакты родителей.')}
        actions={
          <>
            <Button icon={BookOpen} onClick={() => window.open(data.docs_url, '_blank', 'noopener')}>{t('Документация')}</Button>
            <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>{t('Новый ключ')}</Button>
          </>
        }
      />
      <div className="space-y-4">
        {!data.enabled && (
          <div className="rounded-xl bg-warning-50 px-4 py-3 text-[13px] text-warning-700">
            {t('Публичное API — на тарифе Enterprise. Ключи можно выпустить заранее: заработают, когда тариф подключат.')}
          </div>
        )}

        <Card padded={false}>
          <CardHeader className="mb-0 px-5 pt-5" title={t('Действующие ключи')} />
          {active.length === 0 ? (
            <EmptyState icon={KeyRound} title={t('Ключей нет')} description={t('Выпустите ключ для программы, которой нужны данные центра.')} />
          ) : (
            <ul className="divide-y divide-line">
              {active.map(key => <KeyRow key={key.id} row={key} onRevoke={() => revoke(key)} />)}
            </ul>
          )}
        </Card>

        <Card padded={false}>
          <CardHeader className="mb-0 px-5 pt-5" title={t('Последние обращения')} description={t('Кто и что запрашивал — для разбора проблем.')} />
          {log.length === 0 ? (
            <p className="px-5 pb-5 text-[13px] text-ink-muted">{t('Обращений пока не было.')}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[34rem] text-[13px]">
                <tbody className="divide-y divide-line">
                  {log.slice(0, 50).map(row => (
                    <tr key={row.id}>
                      <td className="whitespace-nowrap px-5 py-2 text-ink-muted">{formatDateTime(row.created_at)}</td>
                      <td className="px-2 py-2 text-ink">{row.key}</td>
                      <td className="px-2 py-2 font-mono text-[12px] text-ink">{row.method} {row.path}</td>
                      <td className="px-5 py-2 text-right">
                        <Badge tone={row.status < 300 ? 'success' : row.status === 429 ? 'warning' : 'danger'}>{row.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {revoked.length > 0 && (
          <Card padded={false}>
            <CardHeader className="mb-0 px-5 pt-5" title={t('Отозванные')} />
            <ul className="divide-y divide-line opacity-70">
              {revoked.map(key => <KeyRow key={key.id} row={key} />)}
            </ul>
          </Card>
        )}
      </div>

      {creating && (
        <CreateKeyModal
          branches={data.branches}
          onClose={() => setCreating(false)}
          onCreated={key => { setCreating(false); setIssued(key); load() }}
        />
      )}
      {issued && <IssuedKeyModal issued={issued} onClose={() => setIssued(null)} />}
    </div>
  )
}

function KeyRow({ row, onRevoke }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3">
      <div className="min-w-[12rem] flex-1">
        <p className="text-sm font-semibold text-ink">{row.name} <code className="ml-1 text-[12px] font-normal text-ink-muted">{row.prefix}…</code></p>
        <p className="text-[12px] text-ink-muted">
          {t(row.scope_label)} · {row.branches.length ? row.branches.map(b => b.name).join(', ') : t('все филиалы')}
          {' · '}
          {row.revoked_at
            ? t('отозван {when}', { when: formatDateTime(row.revoked_at) })
            : row.last_used_at ? t('использован {when}', { when: formatDateTime(row.last_used_at) }) : t('ещё не использовался')}
        </p>
      </div>
      {onRevoke && <Button size="sm" variant="danger-ghost" icon={ShieldOff} onClick={onRevoke}>{t('Отозвать')}</Button>}
    </li>
  )
}

function CreateKeyModal({ branches, onClose, onCreated }) {
  const toast = useToast()
  const [name, setName] = useState('')
  const [scope, setScope] = useState('read')
  const [chosen, setChosen] = useState([])
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const res = await api.post('api-keys/', { name, scope, branches: chosen })
      onCreated(res.data)
    } catch (err) {
      const data = err.response?.data || {}
      if (data.name || data.scope || data.branches) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const scopes = [
    { key: 'read', label: t('Только чтение'), hint: t('Дети, группы, расписание, посещаемость, абонементы, оплаты.') },
    { key: 'read_write', label: t('Чтение и запись'), hint: t('Плюс создание заявок — например, с формы партнёра.') },
  ]

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={t('Новый ключ')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="api-key-form" loading={saving}>{t('Выпустить')}</Button>
        </>
      }
    >
      <form id="api-key-form" onSubmit={submit} className="space-y-4">
        <Field label={t('Название')} required error={errors.name?.[0]} hint={t('Чтобы потом узнать: «Сайт», «1С», «Отчёты»')}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={name} onChange={e => setName(e.target.value)} maxLength={100} required autoFocus />}
        </Field>
        <div>
          <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Доступ')}</p>
          <div className="space-y-2">
            {scopes.map(option => (
              <button
                key={option.key}
                type="button"
                onClick={() => setScope(option.key)}
                className={cn('w-full rounded-lg border-[1.5px] px-3 py-2 text-left', scope === option.key ? 'border-brand-400 bg-brand-50' : 'border-line')}
              >
                <span className="block text-sm font-semibold text-ink">{option.label}</span>
                <span className="block text-[12px] text-ink-muted">{option.hint}</span>
              </button>
            ))}
          </div>
        </div>
        <div>
          <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Филиалы')}</p>
          <p className="mb-2 text-[12px] text-ink-muted">{t('Ничего не выбрано — все филиалы.')}</p>
          <div className="space-y-1.5">
            {branches.map(branch => (
              <Checkbox
                key={branch.id}
                checked={chosen.includes(branch.id)}
                onChange={e => setChosen(e.target.checked ? [...chosen, branch.id] : chosen.filter(id => id !== branch.id))}
                label={<span className="text-sm text-ink">{branch.name}</span>}
              />
            ))}
          </div>
        </div>
      </form>
    </Modal>
  )
}

function IssuedKeyModal({ issued, onClose }) {
  const toast = useToast()
  async function copy() {
    try {
      await navigator.clipboard.writeText(issued.key)
      toast.success(t('Ключ скопирован'))
    } catch {
      toast.error(t('Не удалось скопировать — выделите и скопируйте вручную'))
    }
  }
  return (
    <Modal open onClose={onClose} size="sm" title={t('Ключ «{name}» выпущен', { name: issued.name })} footer={<Button variant="primary" onClick={onClose}>{t('Я сохранил ключ')}</Button>}>
      <p className="text-sm text-ink">{t('Скопируйте ключ сейчас — больше мы его не покажем. Потеряли — отзовите и выпустите новый.')}</p>
      <div className="mt-3 flex items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded-md border border-line bg-surface-muted px-3 py-2 text-[12px] text-ink">{issued.key}</code>
        <Button size="sm" icon={Copy} onClick={copy}>{t('Копировать')}</Button>
      </div>
      <p className="mt-3 text-[12px] text-ink-muted">{t('Не публикуйте ключ на сайте и в открытом коде: по нему видны данные детей центра.')}</p>
    </Modal>
  )
}
