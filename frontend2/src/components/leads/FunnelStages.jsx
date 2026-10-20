import { useCallback, useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Eye, EyeOff, Pencil, Trash2 } from 'lucide-react'
import api from '../../api/axios'
import { Badge, Button, DataTable, Field, Input, Modal, Select, apiErrorMessage, cn, plural, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'
import { STAGE_COLORS, STAGE_DOT } from './format'

// Роли, внутри которых центр может добавить свой этап (LeadStage.CUSTOM_ROLES).
const CUSTOM_ROLES = ['new', 'contacted', 'trial_scheduled', 'trial_attended', 'thinking']

/**
 * Этапы воронки центра (TRU-154). Основные этапы держат смысл воронки —
 * пробные, продажу, отказы и аналитику, поэтому их можно переименовать,
 * перекрасить и переставить, но не скрыть. Свои этапы живут внутри
 * основного: «Тестирование уровня» — это ещё «Связались» для отчётов.
 *
 * Та же таблица, что у остальных справочников продаж; «Добавить» — в
 * шапке страницы (creating / onCreatingChange), число этапов — onLoaded.
 */
export default function FunnelStages({ creating = false, onCreatingChange, onLoaded }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [stages, setStages] = useState(null)
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(null)

  const fetchStages = useCallback(() => api.get('leads/stages/').then(res => {
    setStages(res.data)
    onLoaded?.(res.data)
  }).catch(() => setError(true)), [onLoaded])
  useEffect(() => { fetchStages() }, [fetchStages])
  const retry = () => { setError(false); fetchStages() }

  const roleName = role => stages?.find(s => s.is_system && s.role === role)?.name || role
  const modal = creating ? 'new' : editing
  const closeModal = () => { setEditing(null); onCreatingChange?.(false) }

  async function run(key, request, success) {
    setBusy(key)
    try {
      await request()
      if (success) toast.success(success)
      await fetchStages()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  function moveStage(index, delta) {
    const ids = stages.map(s => s.id)
    const [id] = ids.splice(index, 1)
    ids.splice(index + delta, 0, id)
    run(`move:${id}`, () => api.post('leads/stages/reorder/', { ids }))
  }

  async function toggleHidden(stage) {
    if (!stage.is_hidden && stage.lead_count > 0) {
      const ok = await confirm({
        title: t('Скрыть этап?'),
        message: t('{n} на этапе «{name}» перейдут на «{main}».', {
          n: `${stage.lead_count} ${plural(stage.lead_count, ['заявка', 'заявки', 'заявок'])}`,
          name: stage.name,
          main: roleName(stage.role),
        }),
        confirmText: t('Скрыть'),
      })
      if (!ok) return
    }
    run(`hide:${stage.id}`, () => api.patch(`leads/stages/${stage.id}/`, { is_hidden: !stage.is_hidden }), stage.is_hidden ? t('Этап снова в воронке') : t('Этап скрыт'))
  }

  async function remove(stage) {
    const ok = await confirm({ title: t('Удалить этап?'), message: t('Этап «{name}» пропадёт из воронки.', { name: stage.name }), confirmText: t('Удалить'), danger: true })
    if (ok) run(`delete:${stage.id}`, () => api.delete(`leads/stages/${stage.id}/`), t('Этап удалён'))
  }

  const columns = [
    {
      key: 'name',
      header: t('Название'),
      primary: true,
      render: stage => (
        <span className={cn('inline-flex min-w-0 items-center gap-2.5', stage.is_hidden && 'opacity-60')}>
          <span className={cn('size-2.5 shrink-0 rounded-full', STAGE_DOT[stage.color])} />
          <span className="min-w-0">
            <span className="block truncate font-semibold text-ink">{stage.name}</span>
            {!stage.is_system && <span className="block text-xs font-normal text-ink-muted">{t('Внутри «{main}»', { main: roleName(stage.role) })}</span>}
          </span>
        </span>
      ),
    },
    { key: 'usage', header: t('Использовано'), render: stage => <span className="text-ink-muted">{stage.lead_count} {plural(stage.lead_count, ['заявка', 'заявки', 'заявок'])}</span> },
    {
      key: 'status',
      header: t('Статус'),
      mobileAside: true,
      render: stage => (stage.is_hidden
        ? <Badge>{t('Скрыт')}</Badge>
        : stage.is_system ? <Badge tone="success">{t('Основной этап')}</Badge> : <Badge tone="info">{t('Свой этап')}</Badge>),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: stage => {
        const index = stages.indexOf(stage)
        return (
          <span className="inline-flex gap-1" onClick={e => e.stopPropagation()}>
            <Button variant="ghost" size="icon" aria-label={t('Выше')} disabled={index === 0 || busy !== null} onClick={() => moveStage(index, -1)}><ArrowUp className="size-4" /></Button>
            <Button variant="ghost" size="icon" aria-label={t('Ниже')} disabled={index === stages.length - 1 || busy !== null} onClick={() => moveStage(index, 1)}><ArrowDown className="size-4" /></Button>
            <Button variant="ghost" size="icon" aria-label={t('Изменить')} onClick={() => setEditing(stage)}><Pencil className="size-4" /></Button>
            {!stage.is_system && (
              <Button variant="ghost" size="icon" aria-label={stage.is_hidden ? t('Показать') : t('Скрыть')} loading={busy === `hide:${stage.id}`} onClick={() => toggleHidden(stage)}>
                {stage.is_hidden ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
              </Button>
            )}
            {!stage.is_system && stage.lead_count === 0 && (
              <Button variant="danger-ghost" size="icon" aria-label={t('Удалить')} loading={busy === `delete:${stage.id}`} onClick={() => remove(stage)}><Trash2 className="size-4" /></Button>
            )}
          </span>
        )
      },
    },
  ]

  return (
    <>
      <DataTable
        columns={columns}
        rows={stages || []}
        loading={!stages && !error}
        error={error}
        onRetry={retry}
        onRowClick={stage => setEditing(stage)}
      />
      {modal && (
        <StageModal
          stage={modal === 'new' ? null : modal}
          roleName={roleName}
          onClose={closeModal}
          onSaved={() => { closeModal(); fetchStages() }}
        />
      )}
    </>
  )
}

function StageModal({ stage, roleName, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({ name: stage?.name || '', color: stage?.color || 'teal', role: stage?.role || 'contacted' })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const payload = stage?.is_system ? { name: form.name, color: form.color } : form
    try {
      if (stage) await api.patch(`leads/stages/${stage.id}/`, payload)
      else await api.post('leads/stages/', payload)
      toast.success(stage ? t('Сохранено') : t('Этап добавлен'))
      onSaved()
    } catch (err) {
      const data = err.response?.data || {}
      if (data.name || data.role) setErrors({ name: data.name?.[0], role: data.role?.[0] })
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={stage ? t('Изменить этап') : t('Новый этап воронки')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="stage-form" loading={saving}>{stage ? t('Сохранить') : t('Добавить')}</Button>
        </>
      }
    >
      <form id="stage-form" onSubmit={submit} className="space-y-4">
        <Field label={t('Название')} required error={errors.name}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={form.name} onChange={e => set('name', e.target.value)} placeholder={t('Например, тестирование уровня')} maxLength={60} required autoFocus />
          )}
        </Field>
        {!stage?.is_system && (
          <Field label={t('Внутри какого этапа')} hint={t('Для отчётов и правил переходов заявка на этом этапе считается здесь.')} error={errors.role}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.role} onChange={e => set('role', e.target.value)}>
                {CUSTOM_ROLES.map(role => <option key={role} value={role}>{roleName(role)}</option>)}
              </Select>
            )}
          </Field>
        )}
        <div>
          <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Цвет')}</p>
          <div className="flex flex-wrap gap-2">
            {STAGE_COLORS.map(color => (
              <button
                key={color.value}
                type="button"
                onClick={() => set('color', color.value)}
                aria-label={color.label}
                aria-pressed={form.color === color.value}
                className={cn('flex size-8 items-center justify-center rounded-full border-2 transition', form.color === color.value ? 'border-ink' : 'border-transparent hover:border-line-strong')}
              >
                <span className={cn('size-4 rounded-full', STAGE_DOT[color.value])} />
              </button>
            ))}
          </div>
        </div>
      </form>
    </Modal>
  )
}
