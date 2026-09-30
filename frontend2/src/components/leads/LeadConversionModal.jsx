import { useEffect, useState } from 'react'
import { Baby, Link2, RefreshCw, UserRoundPlus, Users } from 'lucide-react'
import api from '../../api/axios'
import {
  Badge, Button, Checkbox, DateInput, ErrorState, Field, Input, Modal, Select,
  apiErrorMessage, cn, formatDate, useToast,
} from '../../ui'
import { t } from '../../i18n'
import { personNameInput, personNameInputProps } from '../../utils/formValidation'

const EMPTY = {
  child_name: '', birth_date: '', gender: '', parent_name: '',
  link_role: 'mother', consent_given: false,
}

const ROLE_OPTIONS = [
  ['mother', 'Мама'], ['father', 'Папа'], ['guardian', 'Опекун'],
  ['grandmother', 'Бабушка'], ['other', 'Другое'],
]

export default function LeadConversionModal({ lead, onClose, onConverted, forSale = false }) {
  const toast = useToast()
  const [form, setForm] = useState(EMPTY)
  const [matches, setMatches] = useState([])
  const [choice, setChoice] = useState('')
  const [state, setState] = useState('loading')
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState({})
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))

  useEffect(() => {
    let alive = true
    api.get(`leads/${lead.id}/conversion/`)
      .then(({ data }) => {
        if (!alive) return
        setForm(current => ({ ...current, ...data.defaults }))
        setMatches(data.matches)
        setChoice(data.matches.length ? '' : 'create_new')
        setState('ready')
      })
      .catch(() => { if (alive) setState('error') })
    return () => { alive = false }
  }, [lead.id])

  async function refreshMatches() {
    setState('checking')
    try {
      const { data } = await api.get(`leads/${lead.id}/conversion/`, {
        params: { child_name: form.child_name, birth_date: form.birth_date || undefined },
      })
      setMatches(data.matches)
      setChoice(data.matches.length ? '' : 'create_new')
      setState('ready')
    } catch (err) {
      setState('ready')
      toast.error(apiErrorMessage(err))
    }
  }

  async function submit(e) {
    e.preventDefault()
    if (!choice) {
      setErrors({ decision: [t('Выберите, какую карточку использовать.')] })
      return
    }
    const [decision, targetId] = choice.split(':')
    setSaving(true)
    setErrors({})
    try {
      const { data } = await api.post(`leads/${lead.id}/conversion/`, {
        ...form,
        decision,
        child_id: decision === 'existing_child' ? targetId : undefined,
        parent_id: decision === 'existing_parent' ? targetId : undefined,
      })
      toast.success(t('Карточка клиента создана'))
      onConverted(data)
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
      size="xl"
      title={forSale ? t('Оформить клиента') : t('Оформить клиента после пробного')}
      description={t('Уточните обязательные данные и решите, создавать новую карточку или связать заявку с найденной.')}
      footer={state !== 'loading' && state !== 'error' ? (
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="lead-conversion-form" loading={saving} disabled={!choice}>
            {t('Завершить конвертацию')}
          </Button>
        </>
      ) : null}
    >
      {state === 'loading' ? (
        <p className="py-12 text-center text-sm text-ink-muted">{t('Ищем совпадения…')}</p>
      ) : state === 'error' ? (
        <ErrorState onRetry={() => window.location.reload()} />
      ) : (
        <form id="lead-conversion-form" onSubmit={submit} className="space-y-6">
          <section>
            <h3 className="font-semibold text-ink">{t('Данные ребёнка и родителя')}</h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-2">
              <Field label={t('Фамилия и имя ребёнка')} required error={errors.child_name}>
                {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.child_name} onChange={e => set('child_name', personNameInput(e.target.value))} required minLength={3} {...personNameInputProps} />}
              </Field>
              <Field label={t('Точная дата рождения')} required error={errors.birth_date}>
                {({ id, invalid }) => <DateInput id={id} invalid={invalid} value={form.birth_date} onChange={value => set('birth_date', value)} max={new Date().toISOString().slice(0, 10)} required />}
              </Field>
              <Field label={t('Пол')} required error={errors.gender}>
                {({ id, invalid }) => (
                  <Select id={id} invalid={invalid} value={form.gender} onChange={e => set('gender', e.target.value)} required>
                    <option value="">{t('Выберите')}</option>
                    <option value="female">{t('Девочка')}</option>
                    <option value="male">{t('Мальчик')}</option>
                  </Select>
                )}
              </Field>
              <Field label={t('Фамилия и имя родителя')} required error={errors.parent_name}>
                {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.parent_name} onChange={e => set('parent_name', personNameInput(e.target.value))} required minLength={3} {...personNameInputProps} />}
              </Field>
              <Field label={t('Кем приходится')} required error={errors.link_role}>
                {({ id, invalid }) => (
                  <Select id={id} invalid={invalid} value={form.link_role} onChange={e => set('link_role', e.target.value)} required>
                    {ROLE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{t(label)}</option>)}
                  </Select>
                )}
              </Field>
              <div className="flex items-end pb-0.5">
                <Button type="button" icon={RefreshCw} onClick={refreshMatches} loading={state === 'checking'} disabled={!form.child_name || !form.birth_date}>
                  {t('Проверить совпадения')}
                </Button>
              </div>
              <Checkbox className="sm:col-span-2" label={t('Согласие на обработку персональных данных получено')} checked={form.consent_given} onChange={e => set('consent_given', e.target.checked)} />
              {errors.consent_given && <p className="text-sm text-danger-600 sm:col-span-2">{errors.consent_given[0]}</p>}
            </div>
          </section>

          <section className="border-t border-line pt-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="font-semibold text-ink">{t('Куда сохранить')}</h3>
                <p className="mt-0.5 text-sm text-ink-muted">
                  {matches.length ? t('Найдены похожие записи. Выберите вариант — система ничего не объединит сама.') : t('Совпадений не найдено. Будет создана новая семья.')}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {lead.direction_name && <Badge tone="danger">{lead.direction_name}</Badge>}
                {lead.branch_name && <Badge tone="info">{lead.branch_name}</Badge>}
              </div>
            </div>

            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {matches.map((match, index) => {
                const isFamily = match.reason === 'existing_parent_new_child'
                const value = isFamily ? `existing_parent:${match.parent.id}` : `existing_child:${match.child.id}`
                return (
                  <ChoiceCard key={`${match.reason}-${match.child?.id || match.parent?.id}-${index}`} active={choice === value} onClick={() => setChoice(value)} icon={isFamily ? Users : Link2} title={isFamily ? t('Создать ребёнка в найденной семье') : t('Связать с существующим ребёнком')}>
                    {match.child && <p className="font-semibold text-ink">{match.child.full_name} · {formatDate(match.child.birth_date)}</p>}
                    {match.parent && <p className="text-sm text-ink-muted">{match.parent.full_name} · {match.parent.phones.join(', ')}</p>}
                    <p className="mt-1 text-xs text-ink-subtle">{duplicateReason(match.reason)}</p>
                  </ChoiceCard>
                )
              })}
              <ChoiceCard active={choice === 'create_new'} onClick={() => setChoice('create_new')} icon={matches.length ? UserRoundPlus : Baby} title={matches.length ? t('Всё равно создать новую семью') : t('Создать ребёнка и родителя')}>
                <p className="text-sm text-ink-muted">{form.child_name || t('Новый ребёнок')} · {form.parent_name || t('Новый родитель')}</p>
              </ChoiceCard>
            </div>
            {errors.decision && <p className="mt-2 text-sm text-danger-600">{errors.decision[0]}</p>}
            {errors.non_field_errors && <p className="mt-2 text-sm text-danger-600">{errors.non_field_errors[0]}</p>}
          </section>
        </form>
      )}
    </Modal>
  )
}

function ChoiceCard({ active, onClick, icon: Icon, title, children }) {
  return (
    <button type="button" onClick={onClick} className={cn('rounded-xl border p-4 text-left transition-colors', active ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-100' : 'border-line bg-surface hover:border-brand-300')}>
      <span className="flex items-center gap-2 font-semibold text-ink"><Icon className="size-4 text-brand-600" />{title}</span>
      <div className="mt-2">{children}</div>
    </button>
  )
}

function duplicateReason(reason) {
  const labels = {
    phone: t('Совпали телефон, имя и дата рождения'),
    existing_parent_new_child: t('Телефон уже принадлежит этой семье, ребёнок другой'),
    name_and_birth_date: t('Совпали имя и дата рождения'),
    name_only: t('Совпало имя — проверьте вручную'),
  }
  return labels[reason] || reason
}
