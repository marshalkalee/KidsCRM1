import { useState } from 'react'
import api from '../api/axios'
import { Button, CheckList, Checkbox, Field, Input, Modal, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'
import { entityNameInputProps } from '../utils/formValidation'

export default function SubscriptionTypeModal({ type, directions, branches, onClose, onSaved }) {
  const isEdit = Boolean(type)
  const toast = useToast()
  const [form, setForm] = useState({
    name: type?.name || '',
    price: type?.price || '',
    is_unlimited: type?.is_unlimited || false,
    quota_sessions: type?.quota_sessions ?? '',
    duration_days: type?.duration_days || '',
    directions: (type?.directions || []).map(String),
    branches: (type?.branches || []).map(String),
    is_public: type?.is_public || false,
    freezes_per_year: type?.freezes_per_year ?? '',
    freeze_max_days: type?.freeze_max_days ?? '',
    expire_on_miss: type?.expire_on_miss || false,
    // makeups_limit = 0 на бэке — «отработок нет»; в форме это галочка.
    makeups_enabled: type?.makeups_limit !== 0,
    makeup_window_days: type?.makeup_window_days ?? '',
    makeups_limit: type?.makeups_limit ? type.makeups_limit : '',
  })
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))

  async function submit(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    const { makeups_enabled, ...rest } = form
    const payload = {
      ...rest,
      quota_sessions: form.is_unlimited ? null : Number(form.quota_sessions),
      // Пусто — без ограничения (null снимает правило на бэке).
      freezes_per_year: form.freezes_per_year === '' ? null : Number(form.freezes_per_year),
      freeze_max_days: form.freeze_max_days === '' ? null : Number(form.freeze_max_days),
      makeups_limit: !makeups_enabled ? 0 : form.makeups_limit === '' ? null : Number(form.makeups_limit),
      makeup_window_days: !makeups_enabled || form.makeup_window_days === '' ? null : Number(form.makeup_window_days),
    }
    try {
      const response = isEdit
        ? await api.patch(`subscriptions/subscription-types/${type.id}/`, payload)
        : await api.post('subscriptions/subscription-types/', payload)
      toast.success(isEdit ? t('Тип абонемента сохранён') : t('Тип абонемента создан'))
      onSaved(response.data)
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? t('Редактировать тип абонемента') : t('Новый тип абонемента')}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="subscription-type-form" loading={saving}>
            {isEdit ? t('Сохранить') : t('Создать тип')}
          </Button>
        </>
      }
    >
      {isEdit && (
        <p className="mb-3 text-[13px] text-ink-muted">
          {t('Изменения не затронут уже проданные абонементы — они сохранят прежние условия.')}
        </p>
      )}
      <form id="subscription-type-form" onSubmit={submit} className="flex flex-col gap-3.5">
        <Field label={t('Название')} required error={errors.name}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={form.name} onChange={e => set('name', e.target.value)}
              placeholder={t('8 занятий')} required autoFocus {...entityNameInputProps} />
          )}
        </Field>
        <div className="flex gap-3.5">
          <Field label={t('Цена')} required error={errors.price} className="flex-1">
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} value={form.price} onChange={e => set('price', e.target.value)} required />}
          </Field>
          <Field label={t('Срок действия, дней')} required error={errors.duration_days} className="flex-1">
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} value={form.duration_days} onChange={e => set('duration_days', e.target.value)} required />}
          </Field>
        </div>
        <label className="flex items-center gap-2 text-[13px]">
          <input type="checkbox" checked={form.is_unlimited} onChange={e => set('is_unlimited', e.target.checked)} />
          {t('Безлимитный')}
        </label>
        {!form.is_unlimited && (
          <Field label={t('Занятий в абонементе')} required error={errors.quota_sessions}>
            {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} value={form.quota_sessions} onChange={e => set('quota_sessions', e.target.value)} required />}
          </Field>
        )}
        <div>
          <div className="flex gap-3.5">
            <Field label={t('Заморозок в год')} error={errors.freezes_per_year} className="flex-1">
              {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={0} max={100} value={form.freezes_per_year} onChange={e => set('freezes_per_year', e.target.value)} placeholder={t('Без ограничения')} />}
            </Field>
            <Field label={t('Дней в одной заморозке')} error={errors.freeze_max_days} className="flex-1">
              {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} max={365} value={form.freeze_max_days} onChange={e => set('freeze_max_days', e.target.value)} placeholder={t('Без ограничения')} />}
            </Field>
          </div>
          <p className="mt-1 text-[12px] text-ink-muted">{t('Пусто — без ограничения. 0 заморозок в год — заморозка запрещена.')}</p>
        </div>
        <div className="flex flex-col gap-2.5 rounded-lg bg-surface-muted px-3 py-2.5">
          <div>
            <p className="mb-1 text-sm text-ink">{t('Если ребёнок не пришёл')}</p>
            <div className="flex flex-col gap-1" role="radiogroup" aria-label={t('Если ребёнок не пришёл')}>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="radio" checked={!form.expire_on_miss} onChange={() => set('expire_on_miss', false)} />
                {t('Занятие остаётся на абонементе')}
              </label>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="radio" checked={form.expire_on_miss} onChange={() => set('expire_on_miss', true)} />
                {t('Занятие сгорает')}
              </label>
            </div>
          </div>
          <Checkbox
            checked={form.makeups_enabled}
            onChange={e => set('makeups_enabled', e.target.checked)}
            label={<span className="text-sm text-ink">{t('Разрешить отработки')}</span>}
          />
          {form.makeups_enabled && (
            <div className="flex gap-3.5 pl-7">
              <Field label={t('Срок отработки, дней')} error={errors.makeup_window_days} className="flex-1">
                {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} max={365} value={form.makeup_window_days} onChange={e => set('makeup_window_days', e.target.value)} placeholder="14" />}
              </Field>
              <Field label={t('Отработок за абонемент')} error={errors.makeups_limit} className="flex-1">
                {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" min={1} max={100} value={form.makeups_limit} onChange={e => set('makeups_limit', e.target.value)} placeholder={t('Без ограничения')} />}
              </Field>
            </div>
          )}
        </div>
        <Field label={t('Направления')} error={errors.directions}>
          <CheckList
            empty={t('Нет активных направлений')}
            options={directions.filter(d => d.is_active).map(d => ({ value: d.id, label: d.name }))}
            value={form.directions}
            onChange={v => set('directions', v)}
          />
        </Field>
        <Field label={t('Филиалы')} error={errors.branches}>
          <CheckList
            empty={t('Нет активных филиалов')}
            options={branches.filter(b => b.is_active).map(b => ({ value: b.id, label: b.name }))}
            value={form.branches}
            onChange={v => set('branches', v)}
          />
        </Field>
        <div>
          <Checkbox
            checked={form.is_public}
            onChange={e => set('is_public', e.target.checked)}
            label={<span className="text-sm text-ink">{t('Показывать цену в публичном каталоге')}</span>}
          />
          <p className="mt-1 pl-7 text-[12px] text-ink-muted">{t('По умолчанию цена видна только внутри CRM.')}</p>
        </div>
      </form>
    </Modal>
  )
}
