import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { Button, Field, Input, Modal, Select, Textarea, apiErrorMessage, cn, useToast } from '../../ui'
import { AIBadge, PasteMessage, useAI } from '../ai/ai'
import { t } from '../../i18n'
import { personNameInput, personNameInputProps, phoneDigits, phoneInputProps } from '../../utils/formValidation'

const OPEN_EVENT = 'kc:new-lead'
export const LEAD_CREATED_EVENT = 'kc:lead-created'

/** Открыть «Новую заявку» из любого места (кнопка на доске, в шапке). */
export function openQuickLead() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT))
}

function isTyping(target) {
  return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
}

/**
 * Быстрая заявка (TRU-97): горячая клавиша N (или Alt+N из любого поля),
 * кнопка на доске и сама форма. Живёт в Layout — открывается на любом
 * экране. Кнопку в шапке убрали по просьбе владельца: шапка — для поиска
 * и переключателей, заявку заводят с доски или клавишей.
 */
export function QuickLeadLauncher() {
  const { can } = useSession()
  const [open, setOpen] = useState(false)
  const allowed = can('can_manage_leads')

  useEffect(() => {
    if (!allowed) return undefined
    const onOpen = () => setOpen(true)
    const onKey = e => {
      if (e.code !== 'KeyN' || e.ctrlKey || e.metaKey || e.shiftKey) return
      if (!e.altKey && isTyping(e.target)) return
      if (document.querySelector('[role="dialog"]')) return
      e.preventDefault()
      setOpen(true)
    }
    window.addEventListener(OPEN_EVENT, onOpen)
    document.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener(OPEN_EVENT, onOpen)
      document.removeEventListener('keydown', onKey)
    }
  }, [allowed])

  if (!allowed || !open) return null
  return <QuickLeadModal onClose={() => setOpen(false)} />
}

const EMPTY = { phone: '', parent_name: '', child_name: '', child_age: '', direction: '', source: '', campaign: '' }

function QuickLeadModal({ onClose }) {
  const toast = useToast()
  const navigate = useNavigate()
  const { activeBranchId, branches } = useSession()
  const [form, setForm] = useState(EMPTY)
  const [branch, setBranch] = useState(activeBranchId ? String(activeBranchId) : '')
  const [sources, setSources] = useState([])
  const [campaigns, setCampaigns] = useState([])
  const [directions, setDirections] = useState([])
  const [matches, setMatches] = useState(null)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [more, setMore] = useState(false)
  // Суть запроса от ИИ — сохраняется первым комментарием заявки.
  const [summary, setSummary] = useState('')
  const ai = useAI()
  const phoneRef = useRef(null)
  const set = (key, value) => setForm(f => ({ ...f, [key]: value }))
  // Публикация — внутри источника (TRU-165): сменили источник — публикация сбрасывается.
  const pickSource = value => setForm(f => ({
    ...f,
    source: value,
    campaign: campaigns.some(c => String(c.id) === f.campaign && String(c.source) === value) ? f.campaign : '',
  }))
  const sourceCampaigns = campaigns.filter(c => String(c.source) === form.source)

  // Модалка при открытии фокусирует себя — телефон забираем кадром позже:
  // печатать номер можно сразу, без клика (бюджет — 30 секунд).
  useEffect(() => {
    const frame = requestAnimationFrame(() => phoneRef.current?.focus())
    return () => cancelAnimationFrame(frame)
  }, [])

  useEffect(() => {
    // Источники приходят самыми частыми сверху — первый и есть «по умолчанию».
    api.get('leads/sources/', { params: { active: 1 } }).then(res => {
      setSources(res.data)
      setForm(f => (f.source ? f : { ...f, source: res.data[0] ? String(res.data[0].id) : '' }))
    }).catch(() => {})
    api.get('directions/').then(res => setDirections((res.data.results || res.data).filter(d => d.is_active))).catch(() => {})
    api.get('leads/campaigns/', { params: { active: 1 } }).then(res => setCampaigns(res.data)).catch(() => {})
  }, [])

  // Дубли по телефону — пока вводят, с паузой, чтобы не дёргать сервер на каждую цифру.
  const digits = form.phone.replace(/\D/g, '')
  useEffect(() => {
    if (digits.length < 10) return undefined
    const timer = setTimeout(() => {
      api.get('leads/check-phone/', { params: { phone: digits } }).then(res => setMatches(res.data)).catch(() => setMatches(null))
    }, 300)
    return () => clearTimeout(timer)
  }, [digits])
  const shownMatches = digits.length >= 10 ? matches : null

  async function save(again) {
    setSaving(true)
    setErrors({})
    const payload = {
      phone: form.phone,
      parent_name: form.parent_name,
      child_name: form.child_name,
      child_age: form.child_age === '' ? null : Number(form.child_age),
      direction: form.direction || null,
      source: form.source || null,
      campaign: form.campaign || null,
      branch: branch || null,
    }
    try {
      const res = await api.post('leads/', payload)
      if (summary.trim()) await api.post(`leads/${res.data.id}/comments/`, { text: summary.trim() }).catch(() => {})
      toast.success(t('Заявка сохранена'))
      window.dispatchEvent(new CustomEvent(LEAD_CREATED_EVENT))
      if (again) {
        setForm(f => ({ ...EMPTY, source: f.source }))
        setSummary('')
        setMatches(null)
        phoneRef.current?.focus()
      } else {
        onClose()
        navigate(`/leads/${res.data.id}`)
      }
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const topSources = sources.slice(0, 5)
  const otherSources = sources.slice(5)
  const fieldError = key => (errors[key] ? t(errors[key][0]) : null)

  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={t('Новая заявка')}
      description={t('Обязательны только телефон и имя — остальное можно дописать потом.')}
      footer={
        <>
          <Button onClick={() => save(true)} loading={saving}>{t('Сохранить и ещё')}</Button>
          <Button variant="primary" type="submit" form="quick-lead-form" loading={saving}>{t('Сохранить')}</Button>
        </>
      }
    >
      <form id="quick-lead-form" onSubmit={e => { e.preventDefault(); save(false) }} className="space-y-4">
        {ai.enabled && (
          <PasteMessage
            onParsed={fields => {
              // Заполняем только то, что ИИ нашёл, — уже введённое руками не затираем пустым.
              setForm(f => ({
                ...f,
                phone: fields.phone || f.phone,
                parent_name: fields.parent_name || f.parent_name,
                child_name: fields.child_name || f.child_name,
                child_age: fields.child_age ?? f.child_age,
                direction: fields.direction || f.direction,
                source: fields.source || f.source,
                // Код публикации из ссылки под роликом (K12) — сервер нашёл его в сообщении.
                campaign: fields.campaign || (fields.source && fields.source !== f.source ? '' : f.campaign),
              }))
              if (fields.summary) setSummary(fields.summary)
              if (fields.child_name || fields.child_age || fields.direction) setMore(true)
            }}
          />
        )}
        <Field label={t('Телефон')} required error={fieldError('phone')}>
          {({ id, invalid }) => (
            <Input
              id={id}
              ref={phoneRef}
              invalid={invalid}
              autoComplete="off"
              placeholder="77000000000"
              value={form.phone}
              onChange={e => set('phone', phoneDigits(e.target.value))}
              className="h-11 text-base"
              autoFocus
              required
              {...phoneInputProps}
            />
          )}
        </Field>
        {shownMatches && (shownMatches.leads.length > 0 || shownMatches.parents.length > 0) && <PhoneMatches matches={shownMatches} onNavigate={onClose} />}
        <Field label={t('Имя родителя')} required error={fieldError('parent_name')}>
          {({ id, invalid }) => (
            <Input id={id} invalid={invalid} value={form.parent_name} onChange={e => set('parent_name', personNameInput(e.target.value))} placeholder={t('Как обращаться')} className="h-11 text-base" required {...personNameInputProps} />
          )}
        </Field>

        {sources.length > 0 && (
          <div>
            <p className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{t('Источник')}</p>
            <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={t('Источник')}>
              {topSources.map(source => (
                <SourceChip key={source.id} source={source} active={form.source === String(source.id)} onPick={() => pickSource(String(source.id))} />
              ))}
              {otherSources.length > 0 && (
                <Select aria-label={t('Другой источник')} value={otherSources.some(s => String(s.id) === form.source) ? form.source : ''} onChange={e => e.target.value && pickSource(e.target.value)} className="!h-8 !w-auto">
                  <option value="">{t('Ещё…')}</option>
                  {otherSources.map(s => <option key={s.id} value={s.id}>{t(s.name)}</option>)}
                </Select>
              )}
            </div>
          </div>
        )}

        {sourceCampaigns.length > 0 && (
          <Field label={t('Публикация')} hint={t('С какого ролика или поста пришли — если родитель сказал')} error={fieldError('campaign')}>
            {({ id, invalid }) => (
              <Select id={id} invalid={invalid} value={form.campaign} onChange={e => set('campaign', e.target.value)}>
                <option value="">{t('Не знаем')}</option>
                {sourceCampaigns.map(c => <option key={c.id} value={c.id}>{c.name} · {c.code}</option>)}
              </Select>
            )}
          </Field>
        )}

        {summary && (
          <Field label={<span className="inline-flex items-center gap-2">{t('Комментарий')} <AIBadge /></span>}>
            {({ id }) => <Textarea id={id} rows={2} value={summary} onChange={e => setSummary(e.target.value)} />}
          </Field>
        )}

        {more ? (
          <div className="space-y-4 border-t border-line pt-4">
            <div className="grid grid-cols-[1fr_96px] gap-3">
              <Field label={t('Имя ребёнка')} error={fieldError('child_name')}>
                {({ id, invalid }) => <Input id={id} invalid={invalid} value={form.child_name} onChange={e => set('child_name', personNameInput(e.target.value))} {...personNameInputProps} />}
              </Field>
              <Field label={t('Возраст')} error={fieldError('child_age')}>
                {({ id, invalid }) => <Input id={id} invalid={invalid} type="number" inputMode="numeric" min={1} max={25} value={form.child_age} onChange={e => set('child_age', e.target.value)} />}
              </Field>
            </div>
            <Field label={t('Направление')} error={fieldError('direction')}>
              {({ id, invalid }) => (
                <Select id={id} invalid={invalid} value={form.direction} onChange={e => set('direction', e.target.value)}>
                  <option value="">{t('Не выбрано')}</option>
                  {directions.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </Select>
              )}
            </Field>
            {branches.length > 1 && (
              <Field label={t('Филиал')} error={fieldError('branch')}>
                {({ id, invalid }) => (
                  <Select id={id} invalid={invalid} value={branch} onChange={e => setBranch(e.target.value)}>
                    <option value="">{t('Не выбран')}</option>
                    {branches.map(b => <option key={b.id} value={String(b.id)}>{b.name}</option>)}
                  </Select>
                )}
              </Field>
            )}
          </div>
        ) : (
          <button type="button" onClick={() => setMore(true)} className="text-[13px] font-semibold text-brand-600 hover:underline">
            {t('+ Ребёнок, возраст, направление')}
          </button>
        )}
      </form>
    </Modal>
  )
}

function SourceChip({ source, active, onPick }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      onClick={onPick}
      className={cn(
        'h-8 rounded-full border-[1.5px] px-3 text-[13px] font-semibold transition-colors',
        active ? 'border-brand-400 bg-brand-50 text-brand-600' : 'border-line bg-surface text-ink-muted hover:text-ink',
      )}
    >
      {t(source.name)}
    </button>
  )
}

/** Уже есть с этим номером — показываем до сохранения (дубли). */
function PhoneMatches({ matches, onNavigate }) {
  return (
    <div className="rounded-lg border border-warning-600/30 bg-warning-50 px-3.5 py-3 text-[13px] text-ink">
      <p className="mb-1.5 flex items-center gap-1.5 font-semibold text-warning-600">
        <AlertTriangle className="size-4" />
        {t('Этот номер уже есть')}
      </p>
      <ul className="space-y-1">
        {matches.leads.map(lead => (
          <li key={lead.id}>
            {t('Заявка')}: <span className="font-semibold">{lead.child_name || lead.parent_name}</span>
            {lead.child_name && <span className="text-ink-muted"> · {lead.parent_name}</span>}
            <span className="text-ink-muted"> — {t(lead.status_label)}</span>
          </li>
        ))}
        {matches.parents.map(parent => (
          <li key={parent.id}>
            {t('Клиент')}: <Link to={`/parents/${parent.id}`} onClick={onNavigate} className="font-semibold text-brand-600 hover:underline">{parent.full_name}</Link>
            {parent.children.length > 0 && <span className="text-ink-muted"> · {parent.children.map(c => c.full_name).join(', ')}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}
