import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, Megaphone, Paperclip, Pencil, Plus, Trash2, Users } from 'lucide-react'
import api from '../api/axios'
import { fetchBranches, fetchDirections, fetchGroups } from '../api/lessons'
import {
  Badge, Button, Card, DateInput, EmptyState, ErrorState, Field, Input, Modal, PageHeader, Select, Skeleton, Textarea,
  apiErrorMessage, cn, formatDate, formatDateTime, plural, useConfirm, useToast,
} from '../ui'
import { t } from '../i18n'

/*
 * Объявления центра для кабинета родителя (TRU-140): концерт, праздничное
 * расписание, сбор на костюмы. Кому — весь центр, филиал, направление
 * или группа. Черновик → «Опубликовать»: родители видят объявление в
 * кабинете (рассылки в WhatsApp нет — V3).
 */

const AUDIENCES = [
  { value: 'organization', get label() { return t('Весь центр') } },
  { value: 'branch', get label() { return t('Филиал') } },
  { value: 'direction', get label() { return t('Направление') } },
  { value: 'group', get label() { return t('Группа') } },
]

const EMPTY = { title: '', body: '', audience: 'organization', branch: '', direction: '', group: '', expires_on: '', attachment_url: '', attachment_name: '' }

export default function Announcements() {
  const toast = useToast()
  const confirm = useConfirm()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = useCallback(() => {
    api.get('announcements/')
      .then(({ data }) => { setRows(data.results || data); setError(false) })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  async function act(row, action) {
    try {
      await api.post(`announcements/${row.id}/${action}/`)
      toast.success(action === 'publish' ? t('Опубликовано — родители увидят в кабинете') : t('Снято с публикации'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function remove(row) {
    const ok = await confirm({ title: t('Удалить объявление?'), message: row.title, confirmText: t('Удалить'), danger: true })
    if (!ok) return
    try {
      await api.delete(`announcements/${row.id}/`)
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('Объявления')}
        description={t('Родители видят их в кабинете — только те, кому адресовано.')}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing(EMPTY)}>{t('Новое объявление')}</Button>}
      />
      {error && <Card><ErrorState onRetry={load} /></Card>}
      {!error && rows === null && <Skeleton className="h-40" />}
      {!error && rows?.length === 0 && (
        <Card>
          <EmptyState
            icon={Megaphone}
            title={t('Объявлений пока нет')}
            description={t('Концерт, праздничное расписание, сбор на костюмы — напишите один раз, родители увидят в кабинете.')}
            action={<Button variant="primary" icon={Plus} onClick={() => setEditing(EMPTY)}>{t('Новое объявление')}</Button>}
          />
        </Card>
      )}
      {rows?.length > 0 && (
        <div className="space-y-3">
          {rows.map(row => {
            const expired = row.expires_on && row.expires_on < new Date().toISOString().slice(0, 10)
            return (
              <Card key={row.id}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-base font-bold text-ink">{row.title}</p>
                      <Badge tone={row.status === 'published' ? (expired ? 'neutral' : 'success') : 'warning'}>
                        {row.status === 'published' ? (expired ? t('В архиве') : t('Опубликовано')) : t('Черновик')}
                      </Badge>
                    </div>
                    {row.body && <p className="line-clamp-2 whitespace-pre-line text-sm text-ink-muted">{row.body}</p>}
                    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
                      <span className="inline-flex items-center gap-1"><Users className="size-3.5" />{t(row.audience_display)}{row.target_name ? `: ${row.target_name}` : ''} · {t('увидят {n} {word}', { n: row.reach, word: plural(row.reach, ['ребёнок', 'ребёнка', 'детей']) })}</span>
                      {row.expires_on && <span className="inline-flex items-center gap-1"><CalendarClock className="size-3.5" />{t('актуально до {date}', { date: formatDate(row.expires_on) })}</span>}
                      {row.attachment_url && <a href={row.attachment_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline"><Paperclip className="size-3.5" />{row.attachment_name || t('Вложение')}</a>}
                      {row.published_at && <span>{t('опубликовано {date}', { date: formatDateTime(row.published_at) })}</span>}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {row.status === 'published'
                      ? <Button size="sm" variant="ghost" onClick={() => act(row, 'unpublish')}>{t('Снять')}</Button>
                      : <Button size="sm" variant="primary" onClick={() => act(row, 'publish')}>{t('Опубликовать')}</Button>}
                    <Button size="sm" icon={Pencil} onClick={() => setEditing({ ...EMPTY, ...row, branch: row.branch || '', direction: row.direction || '', group: row.group || '', expires_on: row.expires_on || '' })}>{t('Изменить')}</Button>
                    <Button size="sm" variant="ghost" icon={Trash2} aria-label={t('Удалить')} onClick={() => remove(row)} />
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
      {editing && <AnnouncementForm initial={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />}
    </div>
  )
}

function AnnouncementForm({ initial, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState(initial)
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [options, setOptions] = useState({ branch: [], direction: [], group: [] })

  useEffect(() => {
    Promise.all([fetchBranches(), fetchDirections(), fetchGroups()])
      .then(([branch, direction, group]) => setOptions({ branch, direction, group: group.filter(g => g.status !== 'archived') }))
      .catch(() => {})
  }, [])

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  const target = form.audience === 'organization' ? null : form.audience

  async function upload(event) {
    const file = event.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const body = new FormData()
      body.append('file', file)
      const { data } = await api.post('announcements/attachment/', body)
      setForm(f => ({ ...f, attachment_url: data.url, attachment_name: data.name }))
    } catch (err) {
      toast.error(err.response?.data?.file?.[0] || apiErrorMessage(err))
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  async function save(publish) {
    setBusy(true)
    setErrors({})
    const payload = {
      title: form.title,
      body: form.body,
      audience: form.audience,
      branch: form.branch || null,
      direction: form.direction || null,
      group: form.group || null,
      expires_on: form.expires_on || null,
      attachment_url: form.attachment_url,
      attachment_name: form.attachment_name,
    }
    try {
      const { data } = form.id
        ? await api.patch(`announcements/${form.id}/`, payload)
        : await api.post('announcements/', payload)
      if (publish && data.status !== 'published') await api.post(`announcements/${data.id}/publish/`)
      toast.success(publish ? t('Опубликовано — родители увидят в кабинете') : t('Сохранено'))
      onSaved()
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const published = form.status === 'published'
  return (
    <Modal
      open
      onClose={onClose}
      title={form.id ? t('Объявление') : t('Новое объявление')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          {!published && <Button loading={busy} onClick={() => save(false)}>{t('Сохранить черновик')}</Button>}
          <Button variant="primary" loading={busy} onClick={() => save(true)}>{published ? t('Сохранить') : t('Опубликовать')}</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t('Заголовок')} required error={errors.title}>
          {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.title} onChange={e => set('title', e.target.value)} maxLength={200} placeholder={t('Например: Отчётный концерт 25 декабря')} autoFocus />}
        </Field>
        <Field label={t('Текст')} error={errors.body}>
          {({ id }) => <Textarea id={id} rows={5} value={form.body} onChange={e => set('body', e.target.value)} placeholder={t('Когда, где, что взять с собой')} />}
        </Field>

        <div className="flex flex-col gap-[5px]">
          <p className="font-btn text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Кому')}</p>
          <div role="radiogroup" aria-label={t('Кому')} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {AUDIENCES.map(a => (
              <button
                key={a.value}
                type="button"
                role="radio"
                aria-checked={form.audience === a.value}
                onClick={() => set('audience', a.value)}
                className={cn('h-10 rounded-md border-[1.5px] text-[13px] font-semibold', form.audience === a.value ? 'border-brand-400 bg-brand-50 text-brand-700' : 'border-line-strong text-ink-muted')}
              >
                {a.label}
              </button>
            ))}
          </div>
        </div>
        {target && (
          <Field label={AUDIENCES.find(a => a.value === target).label} required error={errors[target]}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form[target]} onChange={e => set(target, e.target.value)}>
                <option value="">{t('Выберите…')}</option>
                {/* Одноимённые группы бывают в разных филиалах — подписываем филиал. */}
                {options[target].map(o => <option key={o.id} value={o.id}>{target === 'group' && o.branch_name ? `${o.name} · ${o.branch_name}` : o.name}</option>)}
              </Select>
            )}
          </Field>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('Актуально до')} hint={t('После этой даты — в архиве кабинета')} error={errors.expires_on}>
            {({ id, invalid }) => <DateInput id={id} invalid={invalid} value={form.expires_on} onChange={value => set('expires_on', value)} min={new Date().toISOString().slice(0, 10)} />}
          </Field>
          <Field label={t('Афиша или файл')} hint={t('Картинка или PDF до 10 МБ')}>
            {() => (
              form.attachment_url ? (
                <div className="flex h-[38px] items-center gap-2 text-sm">
                  <a href={form.attachment_url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate font-semibold text-brand-700"><Paperclip className="mr-1 inline size-3.5" />{form.attachment_name}</a>
                  <button type="button" onClick={() => setForm(f => ({ ...f, attachment_url: '', attachment_name: '' }))} className="text-[13px] font-semibold text-ink-muted hover:text-danger-600">{t('Убрать')}</button>
                </div>
              ) : (
                <label className={cn('flex h-[38px] cursor-pointer items-center gap-2 rounded-md border border-dashed border-line-strong px-3 text-sm text-ink-muted hover:border-brand-300', uploading && 'opacity-60')}>
                  <Paperclip className="size-4" /> {uploading ? t('Загрузка…') : t('Прикрепить')}
                  <input type="file" accept="image/jpeg,image/png,image/webp,application/pdf" className="sr-only" onChange={upload} disabled={uploading} />
                </label>
              )
            )}
          </Field>
        </div>
      </div>
    </Modal>
  )
}
