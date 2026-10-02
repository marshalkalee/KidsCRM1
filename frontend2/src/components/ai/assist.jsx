import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CalendarCheck, Copy, ListChecks, MessageCircle, PhoneCall, RefreshCw, Sparkles, Wand2 } from 'lucide-react'
import api from '../../api/axios'
import { Button, Card, Field, Modal, Select, Textarea, apiErrorMessage, cn, useToast } from '../../ui'
import { t } from '../../i18n'
import { AIBadge, useAI } from './ai'

/*
 * Вторая волна ИИ-помощника (эксперимент): напоминания пачкой, разбор
 * заметки о звонке, «перед звонком», подбор группы, план дня, причина отказа.
 * Всё, что придумала модель, помечено AIBadge и правится перед отправкой.
 */

const AI_BUTTON = 'inline-flex items-center gap-2 rounded-md border border-[#ddd6fe] bg-[#faf5ff] font-semibold text-[#7c3aed] hover:bg-[#f3e8ff] disabled:opacity-60'

export function AIButton({ icon: Icon = Sparkles, busy, className, children, ...props }) {
  return (
    <button type="button" disabled={busy} className={cn(AI_BUTTON, 'h-10 px-4 text-sm', className)} {...props}>
      {busy ? <RefreshCw className="size-4 animate-spin" /> : <Icon className="size-4" />}
      {children}
    </button>
  )
}

function useAICall() {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  async function call(request) {
    setBusy(true)
    try {
      return (await request()).data
    } catch (err) {
      toast.error(apiErrorMessage(err))
      return null
    } finally {
      setBusy(false)
    }
  }
  return [busy, call]
}

function waLink(phone, text) {
  return `https://wa.me/${(phone || '').replace(/\D/g, '')}?text=${encodeURIComponent(text)}`
}

/* --- Напоминания пачкой ------------------------------------------------ */

/** Кнопка на «Детях» при фильтре «долг» или «скоро заканчивается». */
export function RemindersButton({ childIds, kind }) {
  const ai = useAI()
  const [open, setOpen] = useState(false)
  if (!ai.enabled || !childIds.length) return null
  return (
    <>
      <AIButton icon={MessageCircle} onClick={() => setOpen(true)}>
        {kind === 'debt' ? t('Напомнить об оплате') : t('Предложить продление')}
      </AIButton>
      {open && <RemindersModal childIds={childIds} kind={kind} onClose={() => setOpen(false)} />}
    </>
  )
}

function RemindersModal({ childIds, kind, onClose }) {
  const toast = useToast()
  const [language, setLanguage] = useState('ru')
  const [items, setItems] = useState(null)
  const [sent, setSent] = useState({})
  const [busy, call] = useAICall()

  async function generate() {
    const data = await call(() => api.post('ai/reminders/', { children: childIds, kind, language }))
    if (data) setItems(data.items)
  }

  function edit(index, text) {
    setItems(list => list.map((item, i) => (i === index ? { ...item, text } : item)))
  }

  async function copy(text) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('Скопировано'))
    } catch {
      toast.error(t('Не удалось скопировать'))
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={<span className="flex items-center gap-2">{kind === 'debt' ? t('Напоминания об оплате') : t('Предложения продлить')} <AIBadge /></span>}
      description={t('Своё сообщение каждому родителю — с суммой, датой и именем. Проверьте и отправьте в WhatsApp.')}
      footer={!items && <Button variant="primary" icon={Sparkles} loading={busy} onClick={generate}>{t('Составить для {count}', { count: childIds.length })}</Button>}
    >
      {!items ? (
        <Field label={t('Язык')}>
          {({ id }) => (
            <Select id={id} value={language} onChange={e => setLanguage(e.target.value)}>
              <option value="ru">Русский</option>
              <option value="kk">Қазақша</option>
            </Select>
          )}
        </Field>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-ink-muted">
            {t('Отправлено {done} из {total}', { done: Object.keys(sent).length, total: items.length })}
          </p>
          {items.map((item, index) => (
            <div key={item.child} className={cn('rounded-lg border border-line p-3', sent[item.child] && 'opacity-60')}>
              <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-semibold text-ink">
                  <Link to={`/children/${item.child}`} className="hover:text-brand-700">{item.child_name}</Link>
                  <span className="font-normal text-ink-muted"> · {item.parent_name || t('нет плательщика')}{item.phone && `, ${item.phone}`}</span>
                </p>
              </div>
              <Textarea rows={3} value={item.text} onChange={e => edit(index, e.target.value)} aria-label={t('Текст для {name}', { name: item.child_name })} />
              <div className="mt-2 flex justify-end gap-2">
                <Button size="sm" icon={Copy} onClick={() => copy(item.text)}>{t('Копировать')}</Button>
                {item.phone ? (
                  <a
                    href={waLink(item.phone, item.text)}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => setSent(s => ({ ...s, [item.child]: true }))}
                    className="inline-flex h-8 items-center gap-1.5 rounded-md bg-success-600 px-3 text-[13px] font-semibold text-white hover:brightness-95"
                  >
                    <MessageCircle className="size-3.5" /> WhatsApp
                  </a>
                ) : (
                  <span className="self-center text-xs text-ink-subtle">{t('Нет телефона')}</span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

/* --- Заметка о звонке -------------------------------------------------- */

/** «Разобрать заметку»: из сумбурного текста — канал, аккуратная запись и следующий шаг. */
export function NoteHelper({ text, onParsed }) {
  const ai = useAI()
  const [busy, call] = useAICall()
  if (!ai.enabled || text.trim().length < 15) return null
  async function parse() {
    const data = await call(() => api.post('ai/communication-note/', { text }))
    if (!data) return
    const note = data.next_step ? `${data.note}\n${t('Дальше')}: ${data.next_step}` : data.note
    onParsed({ channel: data.channel, note })
  }
  return (
    <AIButton icon={Wand2} busy={busy} onClick={parse} className="h-8 justify-center px-3 text-[13px]">
      {t('Привести в порядок')}
    </AIButton>
  )
}

/* --- Перед звонком ----------------------------------------------------- */

/**
 * «Перед звонком» — кнопка в шапке карточки ребёнка (рядом с «Редактировать»);
 * сводка (посещаемость, деньги, последние разговоры и о чём заговорить)
 * открывается под шапкой — ChildBriefCard.
 */
export function ChildBriefButton({ childId, onLoaded }) {
  const ai = useAI()
  const [busy, call] = useAICall()
  if (!ai.enabled) return null

  async function load() {
    const data = await call(() => api.post(`ai/children/${childId}/brief/`))
    if (data) onLoaded(data)
  }

  return <AIButton icon={PhoneCall} busy={busy} onClick={load}>{t('Перед звонком')}</AIButton>
}

export function ChildBriefCard({ brief, onHide }) {
  return (
    <Card className="mb-6 border-[#ddd6fe] bg-[#fdfbff]">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-[15px] font-bold text-ink"><PhoneCall className="size-4 text-[#7c3aed]" /> {t('Перед звонком')} <AIBadge /></p>
        <button type="button" onClick={onHide} className="text-[13px] font-semibold text-ink-muted hover:text-ink">{t('Скрыть')}</button>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
        {brief.points.map(point => <li key={point}>{point}</li>)}
      </ul>
      {brief.suggestion && (
        <p className="mt-3 rounded-md bg-[#f3e8ff] px-3 py-2 text-sm text-[#5b21b6]"><span className="font-semibold">{t('Предложение')}:</span> {brief.suggestion}</p>
      )}
    </Card>
  )
}

/* --- Подбор группы для заявки ------------------------------------------ */

export function LeadGroups({ leadId }) {
  const ai = useAI()
  const [result, setResult] = useState(null)
  const [busy, call] = useAICall()
  if (!ai.enabled) return null

  async function load() {
    const data = await call(() => api.post(`ai/leads/${leadId}/groups/`))
    if (data) setResult(data)
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-[15px] font-bold text-ink">{t('Подходящие группы')} <AIBadge /></p>
        {result && (
          <button type="button" onClick={load} disabled={busy} className="text-[13px] font-semibold text-[#7c3aed] hover:underline disabled:opacity-50">
            {t('Обновить')}
          </button>
        )}
      </div>
      {!result ? (
        <>
          <p className="mt-1 text-sm text-ink-muted">{t('По возрасту, направлению, свободным местам и пожеланиям из комментариев.')}</p>
          <AIButton icon={CalendarCheck} busy={busy} onClick={load} className="mt-3 w-full justify-center">{t('Подобрать группу')}</AIButton>
        </>
      ) : result.picks.length ? (
        <>
        {result.note && <p className="mt-2 rounded-md bg-[#f3e8ff] px-3 py-2 text-sm text-[#5b21b6]">{result.note}</p>}
        <ul className="mt-2 space-y-2">
          {result.picks.map(pick => (
            <li key={pick.id} className="rounded-md border border-line p-2.5">
              <Link to={`/groups/${pick.id}`} className="font-semibold text-ink hover:text-brand-700">{pick.name}</Link>
              <p className="text-xs text-ink-muted">
                {[pick.branch, pick.schedule, t('свободно: {count}', { count: pick.free })].filter(Boolean).join(' · ')}
              </p>
              {pick.reason && <p className="mt-1 text-sm text-ink">{pick.reason}</p>}
            </li>
          ))}
        </ul>
        </>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">{t(result.note || 'Подходящих групп нет.')}</p>
      )}
    </Card>
  )
}

/* --- План дня ---------------------------------------------------------- */

export function DailyPlan() {
  const ai = useAI()
  const [tasks, setTasks] = useState(null)
  const [done, setDone] = useState({})
  const [busy, call] = useAICall()
  if (!ai.enabled) return null

  async function load() {
    const data = await call(() => api.post('ai/daily-plan/'))
    if (data) {
      setTasks(data.tasks)
      setDone({})
    }
  }

  return (
    <Card className="mb-6 border-[#ddd6fe] bg-[linear-gradient(135deg,#faf5ff,#fff)]">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-[#ede9fe] text-[#7c3aed]"><ListChecks className="size-5" /></span>
          <div>
            <p className="flex items-center gap-2 font-bold text-ink">{t('План на сегодня')} <AIBadge /></p>
            <p className="text-sm text-ink-muted">{t('Долги, заявки, занятия и продления — в порядке важности.')}</p>
          </div>
        </div>
        <AIButton icon={tasks ? RefreshCw : Sparkles} busy={busy} onClick={load}>{tasks ? t('Обновить') : t('Составить план')}</AIButton>
      </div>
      {tasks && (
        <ol className="mt-4 space-y-1.5">
          {tasks.map((task, index) => (
            <li key={task.text} className="flex items-center gap-3 rounded-md bg-surface px-3 py-2 shadow-card">
              <input
                type="checkbox"
                checked={!!done[index]}
                onChange={e => setDone(d => ({ ...d, [index]: e.target.checked }))}
                className="size-4 accent-[#7c3aed]"
                aria-label={t('Сделано')}
              />
              <span className={cn('flex-1 text-sm text-ink', done[index] && 'text-ink-subtle line-through')}>{task.text}</span>
              {task.link && (
                <Link to={task.link} className="shrink-0 text-ink-subtle hover:text-brand-700" aria-label={t('Открыть')}><ArrowRight className="size-4" /></Link>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

/* --- Причина отказа из комментария ------------------------------------- */

export function SuggestReason({ text, kind, onPicked }) {
  const ai = useAI()
  const toast = useToast()
  const [busy, call] = useAICall()
  if (!ai.enabled || text.trim().length < 5) return null
  async function suggest() {
    const data = await call(() => api.post('ai/rejection-reason/', { text, kind }))
    if (!data) return
    if (data.reason) onPicked(data.reason)
    else toast.error(t('Не удалось подобрать причину — выберите вручную'))
  }
  return (
    <AIButton icon={Wand2} busy={busy} onClick={suggest} className="h-8 px-3 text-[13px]">
      {t('Причина по комментарию')}
    </AIButton>
  )
}
