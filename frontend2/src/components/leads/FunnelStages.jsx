import { useCallback, useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Eye, EyeOff, Pencil, Plus, Trash2 } from 'lucide-react'
import api from '../../api/axios'
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Modal, Select, Skeleton, apiErrorMessage, cn, plural, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'
import { STAGE_COLORS, STAGE_DOT } from './format'

// Роли, внутри которых центр может добавить свой этап (LeadStage.CUSTOM_ROLES).
const CUSTOM_ROLES = ['new', 'contacted', 'trial_scheduled', 'trial_attended', 'thinking']

/**
 * Этапы воронки центра (TRU-154). Основные этапы держат смысл воронки —
 * пробные, продажу, отказы и аналитику, поэтому их можно переименовать,
 * перекрасить и переставить, но не скрыть. Свои этапы живут внутри
 * основного: «Тестирование уровня» — это ещё «Связались» для отчётов.
 */
export default function FunnelStages() {
  const toast = useToast()
  const confirm = useConfirm()
  const [stages, setStages] = useState(null)
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(null)

  const fetchStages = useCallback(() => api.get('leads/stages/').then(res => setStages(res.data)).catch(() => setError(true)), [])
  useEffect(() => { fetchStages() }, [fetchStages])
  const retry = () => { setError(false); fetchStages() }

  const roleName = role => stages?.find(s => s.is_system && s.role === role)?.name || role

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

  if (error) return <Card><ErrorState onRetry={retry} /></Card>
  if (!stages) return <Skeleton className="h-96" />

  return (
    <Card>
      <CardHeader
        title={t('Этапы воронки')}
        description={t('Так этапы называются на доске, в таблице и в отчётах. Основные этапы нельзя скрыть — на них держатся пробные, продажи и аналитика; свои этапы добавляются внутрь основных.')}
        actions={<Button variant="primary" size="sm" icon={Plus} onClick={() => setEditing('new')}>{t('Добавить этап')}</Button>}
      />
      <ol className="divide-y divide-line">
        {stages.map((stage, index) => (
          <li key={stage.id} className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5', stage.is_hidden && 'opacity-60')}>
            <span className={cn('size-2.5 shrink-0 rounded-full', STAGE_DOT[stage.color])} />
            {/* min-w: длинное название не сжимается в «Тестирова…» — кнопки уходят на строку ниже. */}
            <div className="min-w-[10rem] flex-1">
              <p className="truncate text-sm font-semibold text-ink">{stage.name}</p>
              <p className="text-xs text-ink-muted">
                {stage.is_system ? t('Основной этап') : t('Внутри «{main}»', { main: roleName(stage.role) })}
                {' · '}
                {stage.lead_count} {plural(stage.lead_count, ['заявка', 'заявки', 'заявок'])}
              </p>
            </div>
            {stage.is_hidden && <Badge>{t('Скрыт')}</Badge>}
            <span className="ml-auto inline-flex gap-1">
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
          </li>
        ))}
      </ol>
      {editing && (
        <StageModal
          stage={editing === 'new' ? null : editing}
          roleName={roleName}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); fetchStages() }}
        />
      )}
    </Card>
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
