import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MessageCircle, Pencil, Phone, Plus, Unlink, UserRound } from 'lucide-react'
import api from '../../api/axios'
import {
  Badge, Button, CONTACT_ROLES, Card, Checkbox, EmptyState, ErrorState, Field, Input, Modal, Select,
  Skeleton, apiErrorMessage, cn, useConfirm, useToast,
} from '../../ui'
import { t } from '../../i18n'

/**
 * Вкладка «Контакты»: родители и контактные лица ребёнка (ChildContact).
 * Плательщик у ребёнка один — сервер сам снимает флаг с прежнего
 * (ChildContact.save), отвязка мягкая и не удаляет самого родителя.
 */
export default function ContactsTab({ child, permissions, onCountChange }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [links, setLinks] = useState(null)
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null) // null | 'new' | link
  const canManage = permissions.can_manage_contacts

  const load = useCallback(() => {
    api.get('clients/child-contacts/', { params: { child: child.id, page_size: 100 } })
      .then(r => {
        const rows = r.data.results || r.data
        setLinks(rows)
        setError(false)
        onCountChange?.(rows.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])

  async function detach(link) {
    const ok = await confirm({
      title: t('Отвязать контакт?'),
      message: t('{name} больше не будет связан(а) с ребёнком. Сам контакт и история оплат сохранятся.', { name: link.parent_contact_full_name }),
      confirmText: t('Отвязать'),
      danger: true,
    })
    if (!ok) return
    try {
      await api.delete(`clients/child-contacts/${link.id}/`)
      toast.success(t('Контакт отвязан'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!links) return <div className="grid gap-3 md:grid-cols-2"><Skeleton className="h-32" /><Skeleton className="h-32" /></div>

  return (
    <>
      {links.length === 0 ? (
        <Card>
          <EmptyState
            icon={UserRound}
            title={t('Контактов пока нет')}
            description={t('Добавьте маму, папу или другого взрослого, кому звонить и кто платит.')}
            action={canManage && <Button variant="primary" size="sm" icon={Plus} onClick={() => setEditing('new')}>{t('Добавить контакт')}</Button>}
          />
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {links.map(link => (
            <ContactCard key={link.id} link={link} canManage={canManage} onEdit={() => setEditing(link)} onDetach={() => detach(link)} />
          ))}
          {canManage && (
            <button
              type="button"
              onClick={() => setEditing('new')}
              className="flex min-h-32 items-center justify-center gap-2 rounded-lg border-2 border-dashed border-line text-sm font-semibold text-ink-muted transition-colors hover:border-brand-400 hover:text-brand-700"
            >
              <Plus className="size-4" /> {t('Добавить контакт')}
            </button>
          )}
        </div>
      )}

      {editing && (
        <ContactModal
          child={child}
          link={editing === 'new' ? null : editing}
          linkedParentIds={links.map(l => l.parent_contact)}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
        />
      )}
    </>
  )
}

function ContactCard({ link, canManage, onEdit, onDetach }) {
  const phones = link.parent_contact_phones
  const whatsapp = link.parent_contact_whatsapp || phones?.[0]?.number
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/parents/${link.parent_contact}`} className="font-semibold text-ink hover:text-brand-700">
            {link.parent_contact_full_name}
          </Link>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge>{CONTACT_ROLES[link.role] || link.role}</Badge>
            {link.is_payer && <Badge tone="brand">{t('Плательщик')}</Badge>}
            {link.is_primary_contact && <Badge tone="info">{t('Основной контакт')}</Badge>}
          </div>
        </div>
        {canManage && (
          <div className="flex shrink-0 gap-1">
            <Button variant="ghost" size="icon" onClick={onEdit} aria-label={t('Изменить')}><Pencil className="size-4" /></Button>
            <Button variant="danger-ghost" size="icon" onClick={onDetach} aria-label={t('Отвязать')}><Unlink className="size-4" /></Button>
          </div>
        )}
      </div>
      {phones && (
        <div className="flex flex-wrap gap-2">
          {phones.map(phone => (
            <a key={phone.number} href={`tel:${phone.number}`} className="inline-flex items-center gap-1.5 rounded-md bg-surface-muted px-2.5 py-1.5 text-[13px] font-medium text-ink hover:bg-brand-50 hover:text-brand-700">
              <Phone className="size-3.5" /> {phone.number}
            </a>
          ))}
          {whatsapp && (
            <a href={`https://wa.me/${whatsapp.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-md bg-success-50 px-2.5 py-1.5 text-[13px] font-medium text-success-600 hover:brightness-95">
              <MessageCircle className="size-3.5" /> WhatsApp
            </a>
          )}
        </div>
      )}
    </Card>
  )
}

const EMPTY_PARENT = { full_name: '', phone: '' }

/**
 * Привязать контакт: существующего родителя (поиск по имени/телефону —
 * тот же поиск, что в шапке) или нового (создаётся и сразу привязывается).
 * Редактирование: роль и флаги — кого привязали, не меняем (для этого
 * отвязка и новая привязка).
 */
function ContactModal({ child, link, linkedParentIds, onClose, onSaved }) {
  const toast = useToast()
  const isEdit = Boolean(link)
  const [mode, setMode] = useState('new')
  const [parent, setParent] = useState(EMPTY_PARENT)
  const [picked, setPicked] = useState(null)
  const [query, setQuery] = useState('')
  const [found, setFound] = useState([])
  const [form, setForm] = useState({
    role: link?.role || 'mother',
    is_payer: link?.is_payer ?? false,
    is_primary_contact: link?.is_primary_contact ?? false,
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (isEdit || mode !== 'existing' || query.trim().length < 3) return undefined
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api.get('clients/search/', { params: { q: query.trim() }, signal: controller.signal })
        .then(r => setFound(r.data.results.filter(item => item.type === 'parent')))
        .catch(() => {})
    }, 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [query, mode, isEdit])

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      if (isEdit) {
        await api.patch(`clients/child-contacts/${link.id}/`, form)
      } else {
        let parentId = picked?.id
        if (mode === 'new') {
          try {
            const created = await api.post('clients/parents/', {
              full_name: parent.full_name,
              phones: [{ number: parent.phone, phone_type: 'mobile' }],
            })
            parentId = created.data.id
          } catch (err) {
            const data = err.response?.data || {}
            setErrors({ full_name: data.full_name, phone: data.phones?.[0]?.number || data.phones, detail: data.detail })
            return
          }
        }
        await api.post('clients/child-contacts/', { child: child.id, parent_contact: parentId, ...form })
      }
      toast.success(isEdit ? t('Контакт обновлён') : t('Контакт добавлен'))
      onSaved()
    } catch (err) {
      const data = err.response?.data
      if (data?.non_field_errors) setErrors({ detail: data.non_field_errors[0] })
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const canSubmit = isEdit || (mode === 'existing' ? Boolean(picked) : parent.full_name.trim() && parent.phone.trim())

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? link.parent_contact_full_name : t('Добавить контакт')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="contact-form" loading={saving} disabled={!canSubmit}>
            {isEdit ? t('Сохранить') : t('Добавить')}
          </Button>
        </>
      }
    >
      <form id="contact-form" onSubmit={submit} className="flex flex-col gap-4">
        {!isEdit && (
          <div className="flex rounded-md border border-line p-0.5" role="group">
            {[['new', t('Новый контакт')], ['existing', t('Уже есть в базе')]].map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
                className={cn('h-8 flex-1 rounded text-[13px] font-medium', mode === value ? 'bg-brand-50 text-brand-700' : 'text-ink-muted hover:text-ink')}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {!isEdit && mode === 'new' && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('ФИО')} required error={errors.full_name}>
              {({ id, invalid }) => <Input id={id} invalid={invalid} value={parent.full_name} onChange={e => setParent(p => ({ ...p, full_name: e.target.value }))} autoFocus />}
            </Field>
            <Field label={t('Телефон')} required error={errors.phone}>
              {({ id, invalid }) => <Input id={id} invalid={invalid} type="tel" inputMode="tel" placeholder="+7 700 000 00 00" value={parent.phone} onChange={e => setParent(p => ({ ...p, phone: e.target.value }))} />}
            </Field>
          </div>
        )}

        {!isEdit && mode === 'existing' && (
          <Field label={t('Найти родителя')} hint={t('Имя или телефон, от 3 символов')}>
            {({ id }) => (
              <div className="flex flex-col gap-2">
                <Input id={id} value={query} onChange={e => { setQuery(e.target.value); setPicked(null) }} autoFocus />
                {query.trim().length >= 3 && (
                  <ul className="max-h-48 overflow-y-auto rounded-md border border-line">
                    {found.length === 0 && <li className="px-3 py-2 text-sm text-ink-muted">{t('Никого не нашли')}</li>}
                    {found.map(item => {
                      const linked = linkedParentIds.includes(item.id)
                      return (
                        <li key={item.id}>
                          <button
                            type="button"
                            disabled={linked}
                            onClick={() => setPicked(item)}
                            className={cn(
                              'flex w-full items-center justify-between px-3 py-2 text-left text-sm disabled:opacity-50',
                              picked?.id === item.id ? 'bg-brand-50 text-brand-700' : 'hover:bg-surface-muted',
                            )}
                          >
                            <span className="font-medium">{item.title}</span>
                            <span className="text-xs text-ink-subtle">{linked ? t('уже привязан') : item.matched_detail}</span>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            )}
          </Field>
        )}

        <Field label={t('Кем приходится')}>
          {({ id }) => (
            <Select id={id} value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
              {Object.entries(CONTACT_ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Select>
          )}
        </Field>
        <div className="flex flex-col gap-2">
          <Checkbox label={t('Плательщик (у ребёнка он один — прежний снимется)')} checked={form.is_payer} onChange={e => setForm(f => ({ ...f, is_payer: e.target.checked }))} />
          <Checkbox label={t('Основной контакт')} checked={form.is_primary_contact} onChange={e => setForm(f => ({ ...f, is_primary_contact: e.target.checked }))} />
        </div>
        {errors.detail && <p className="text-sm text-danger-600">{errors.detail}</p>}
      </form>
    </Modal>
  )
}
