import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, MessageSquarePlus, Plus, Sparkles, Wallet } from 'lucide-react'
import { useSession } from '../../session/SessionContext'
import { Button, Card, cn } from '../../ui'
import { locale, t } from '../../i18n'
import { openQuickLead } from '../leads/QuickLead'
import Markdown from '../ai/Markdown'
import { Message, Sources, Thinking } from '../ai/AIChat'
import { chatSuggestions, useAIConversation } from '../ai/useAIConversation'

/** «Четверг, 1 октября · Dance Kids Almaty» — на языке интерфейса. */
function todayLine(organization) {
  const date = new Date().toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long' })
  const text = date.charAt(0).toUpperCase() + date.slice(1)
  return organization ? `${text} · ${organization}` : text
}

/** Быстрые действия главной — по правам роли. */
function QuickActions() {
  const { can } = useSession()
  return (
    <div className="flex flex-wrap gap-2">
      {can('can_manage_leads') && <Button icon={Plus} onClick={openQuickLead}>{t('Новая заявка')}</Button>}
      {can('can_accept_payments') && <Button to="/money?tab=debts" variant="primary" icon={Wallet}>{t('Принять оплату')}</Button>}
    </div>
  )
}

const CAPTION = 'font-btn text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle'

/** Шапка главной без ИИ: дата, «Сегодня в центре», быстрые действия. */
export function DashboardHeader() {
  const { user } = useSession()
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className={CAPTION}>{todayLine(user?.organization_name)}</p>
        <h1 className="mt-1.5 text-[26px] font-bold leading-tight text-ink">{t('Сегодня в центре')}</h1>
      </div>
      <QuickActions />
    </div>
  )
}

/**
 * Шапка главной с ИИ (вариант B пробника): «Что хотите узнать о центре?»,
 * подсказки и последний ответ. Разговор тот же, что на странице
 * «ИИ-помощник» — там история и полный экран.
 */
export function AIHeader() {
  const { can, user } = useSession()
  const chat = useAIConversation(true)
  const { messages, busy, loading } = chat
  const [draft, setDraft] = useState('')
  const input = useRef(null)

  async function send(text) {
    setDraft('')
    await chat.send(text)
    input.current?.focus()
  }

  const lastAnswerIndex = messages.findLastIndex(m => m.role === 'assistant')
  const lastAnswer = messages[lastAnswerIndex]
  const lastQuestion = [...messages.slice(0, lastAnswerIndex < 0 ? messages.length : lastAnswerIndex)].reverse().find(m => m.role === 'user')
  const pendingQuestion = busy ? messages[messages.length - 1] : null

  return (
    <Card padded={false} className="mb-5 border-[#ebe3f7] px-5 py-5 sm:px-7 sm:py-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className={cn(CAPTION, 'pt-1')}>{todayLine(user?.organization_name)}</p>
        <QuickActions />
      </div>
      <h1 className="mt-3 text-[24px] font-bold leading-tight text-ink sm:text-[26px]">{t('Что хотите узнать о центре?')}</h1>

      <form onSubmit={e => { e.preventDefault(); send(draft) }} className="mt-4">
        <label className="flex items-center gap-2.5 rounded-[14px] border-[1.5px] border-[#d9ccf3] bg-[#fcfbff] py-1.5 pl-4 pr-1.5 focus-within:border-[#a78bfa] focus-within:ring-2 focus-within:ring-[#ede9fe]">
          <span className="sr-only">{t('Вопрос ИИ-помощнику')}</span>
          <Sparkles className="size-[18px] shrink-0 text-[#7c3aed]" />
          <input
            ref={input}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            maxLength={2000}
            placeholder={t('Например: кто не продлил абонемент в этом месяце?')}
            className="h-10 min-w-0 flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-subtle"
          />
          <button type="submit" disabled={busy || loading || !draft.trim()} className="h-10 shrink-0 rounded-[10px] bg-[#7c3aed] px-4 text-sm font-semibold text-white transition hover:bg-[#6d28d9] disabled:opacity-50 sm:px-5">
            {t('Спросить')}
          </button>
        </label>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {chatSuggestions(can).slice(0, 4).map(text => (
          <button key={text} type="button" disabled={busy} onClick={() => send(text)} className="rounded-full border border-[#e4dcf3] bg-surface px-3 py-1.5 text-[13px] text-ink transition hover:border-[#c4b5fd] hover:bg-[#faf5ff] disabled:opacity-60">
            {text}
          </button>
        ))}
      </div>

      {(busy || lastAnswer) && (
        <div className="mt-5 border-t border-dashed border-[#e4dcf3] pt-4" aria-live="polite">
          {busy ? (
            <div className="space-y-3">
              {pendingQuestion && <Message message={pendingQuestion} />}
              <Thinking />
            </div>
          ) : lastAnswer.error ? (
            <Message message={lastAnswer} onRetry={send} />
          ) : (
            <>
              {lastQuestion && <p className={cn(CAPTION, 'mb-2 normal-case tracking-normal text-[12px] font-semibold')}>{t('Вы спросили: «{q}»', { q: lastQuestion.content })}</p>}
              <div className="max-h-72 overflow-y-auto rounded-xl bg-[#fcfbff] px-4 py-3 text-sm text-ink">
                <Markdown text={lastAnswer.content} />
              </div>
              <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                {lastAnswer.sources?.length > 0 ? <Sources sources={lastAnswer.sources} /> : <span />}
                <div className="flex flex-wrap gap-4 text-[13px] font-semibold">
                  <button type="button" onClick={chat.startNew} className="inline-flex items-center gap-1.5 text-ink-muted hover:text-ink">
                    <MessageSquarePlus className="size-4" /> {t('Новый чат')}
                  </button>
                  <Link to="/assistant" className="inline-flex items-center gap-1.5 text-[#7c3aed] hover:text-[#6d28d9]">
                    {t('Продолжить разговор')} <ArrowRight className="size-4" />
                  </Link>
                </div>
              </div>
            </>
          )}
        </div>
      )}
      {!busy && !lastAnswer && chat.conversations?.length > 0 && (
        <Link to="/assistant" className="mt-4 inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#7c3aed] hover:text-[#6d28d9]">
          {t('История чатов')} <ArrowRight className="size-4" />
        </Link>
      )}
    </Card>
  )
}
