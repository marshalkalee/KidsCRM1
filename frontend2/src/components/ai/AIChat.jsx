import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowUp, Eye, History, MessageSquarePlus, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { useSession } from '../../session/SessionContext'
import { Card, Skeleton, cn } from '../../ui'
import { t } from '../../i18n'
import Markdown from './Markdown'
import { chatSuggestions, useAIConversation } from './useAIConversation'
import { useAIChatAvailable } from './useAIChatAvailable'

/*
 * ИИ-помощник на весь экран (страница /assistant): история чатов слева,
 * разговор справа, «← Главная». Тот же разговор, что в вопросе на главной
 * (useAIConversation). ИИ отвечает по живым данным CRM с правами того,
 * кто спрашивает, только читает (backend: ai/chat.py).
 */

function dayLabel(value) {
  const day = new Date(value)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (day.toDateString() === today.toDateString()) return t('Сегодня')
  if (day.toDateString() === yesterday.toDateString()) return t('Вчера')
  return t('Раньше')
}

export default function AIChat() {
  const { can, user } = useSession()
  const available = useAIChatAvailable()
  const chat = useAIConversation(available)
  const { conversations, currentId, messages, loading, busy } = chat
  const [draft, setDraft] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const scroller = useRef(null)
  const input = useRef(null)

  // Пока ИИ думает — вниз, к индикатору; пришёл ответ — к последнему
  // вопросу, чтобы длинный ответ читался с начала.
  useEffect(() => {
    const box = scroller.current
    if (!box) return
    const questions = box.querySelectorAll('[data-question]')
    const last = questions[questions.length - 1]
    const top = !busy && last && messages[messages.length - 1]?.role === 'assistant'
      ? last.offsetTop - box.offsetTop - 12
      : box.scrollHeight
    box.scrollTo({ top, behavior: busy ? 'smooth' : 'auto' })
  }, [messages, busy])

  if (!available) return null

  async function send(text) {
    setDraft('')
    await chat.send(text)
    input.current?.focus()
  }

  function pick(id) {
    setHistoryOpen(false)
    chat.openConversation(id)
  }

  function startNew() {
    setHistoryOpen(false)
    chat.startNew()
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send(draft)
    }
  }

  const firstName = user?.full_name?.split(/\s+/)[0]
  const empty = messages.length === 0

  return (
    <Card padded={false} className="flex h-[calc(100dvh-7.5rem)] min-h-[420px] overflow-hidden">
      <nav
        aria-label={t('История чатов')}
        className={cn(
          'w-full shrink-0 flex-col gap-0.5 overflow-y-auto border-line bg-surface p-3 lg:flex lg:w-72 lg:border-r',
          historyOpen ? 'flex' : 'hidden',
        )}
      >
        <button type="button" onClick={() => setHistoryOpen(false)} className="mb-2 inline-flex h-9 items-center gap-1 self-start rounded-md px-2 text-[13px] font-semibold text-ink-muted hover:text-ink lg:hidden">
          <ArrowLeft className="size-4" /> {t('К чату')}
        </button>
        <button type="button" onClick={startNew} disabled={busy} className="mb-3 flex h-10 items-center justify-center gap-2 rounded-lg bg-[#7c3aed] text-sm font-semibold text-white hover:bg-[#6d28d9] disabled:opacity-60">
          <MessageSquarePlus className="size-4" /> {t('Новый чат')}
        </button>
        {conversations === null ? (
          <Skeleton className="h-24" />
        ) : conversations.length === 0 ? (
          <p className="px-3 py-2 text-[13px] text-ink-subtle">{t('Здесь появятся ваши чаты.')}</p>
        ) : (
          conversations.map((c, i) => (
            <Fragment key={c.id}>
              {(i === 0 || dayLabel(c.updated_at) !== dayLabel(conversations[i - 1].updated_at)) && (
                <p className="px-3 pb-1 pt-3 font-btn text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle first:pt-0">{dayLabel(c.updated_at)}</p>
              )}
              <div className={cn('group flex items-center rounded-lg', c.id === currentId ? 'bg-[#f3e8ff]' : 'hover:bg-canvas')}>
                <button type="button" onClick={() => pick(c.id)} disabled={busy} className={cn('min-w-0 flex-1 truncate px-3 py-2 text-left text-[13.5px]', c.id === currentId ? 'font-semibold text-[#5b21b6]' : 'text-ink')}>
                  {c.title}
                </button>
                <button type="button" onClick={() => chat.remove(c)} aria-label={t('Удалить чат')} className="mr-1 rounded-md p-1.5 text-ink-subtle hover:bg-surface hover:text-danger-600 lg:opacity-0 lg:group-hover:opacity-100">
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            </Fragment>
          ))
        )}
      </nav>

      <div className={cn('min-w-0 flex-1 flex-col', historyOpen ? 'hidden lg:flex' : 'flex')}>
        <header className="flex items-center justify-between gap-3 border-b border-line bg-[linear-gradient(120deg,#f5f3ff,#fdf2f8_60%,#fff)] px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <Link to="/dashboard" aria-label={t('Главная')} className="inline-flex h-9 shrink-0 items-center gap-1 rounded-md border border-line-strong bg-surface px-2.5 text-[13px] font-semibold text-ink hover:border-[#c4b5fd]">
              <ArrowLeft className="size-4" /><span className="hidden sm:inline">{t('Главная')}</span>
            </Link>
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#8b5cf6,#ec4899)] text-white shadow-sm">
              <Sparkles className="size-5" />
            </span>
            <div className="min-w-0">
              <p className="font-bold text-ink">{t('ИИ-помощник')}</p>
              <p className="truncate text-[13px] text-ink-muted">{t('Отвечает по живым данным CRM — видит то же, что и вы')}</p>
            </div>
          </div>
          <button type="button" onClick={() => setHistoryOpen(true)} aria-label={t('История')} className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-semibold text-ink-muted hover:bg-surface hover:text-ink lg:hidden">
            <History className="size-4" /><span className="hidden sm:inline">{t('История')}</span>
          </button>
        </header>

        <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto bg-canvas/40 px-4 py-4 sm:px-5" aria-live="polite">
          {loading ? (
            <div className="space-y-3"><Skeleton className="ml-auto h-10 w-1/2" /><Skeleton className="h-24 w-4/5" /></div>
          ) : empty ? (
            <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center gap-5 py-2">
              <div>
                <p className="text-lg font-bold text-ink">{firstName ? t('Здравствуйте, {name}!', { name: firstName }) : t('Здравствуйте!')}</p>
                <p className="mt-1 text-sm text-ink-muted">{t('Спросите о детях, долгах, заявках, расписании или выручке — посмотрю в CRM и отвечу. Ничего не меняю, только читаю.')}</p>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {chatSuggestions(can).map(text => (
                  <button key={text} type="button" onClick={() => send(text)} className="rounded-lg border border-line bg-surface px-3.5 py-2.5 text-left text-sm font-medium text-ink shadow-card transition hover:border-[#c4b5fd] hover:bg-[#faf5ff]">
                    {text}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => <Message key={i} message={m} onRetry={send} />)
          )}
          {busy && <Thinking />}
        </div>

        <form onSubmit={e => { e.preventDefault(); send(draft) }} className="border-t border-line bg-surface px-3 py-3 sm:px-4">
          <div className="flex items-end gap-2 rounded-xl border border-line-strong bg-surface px-3 py-2 focus-within:border-[#a78bfa] focus-within:ring-2 focus-within:ring-[#ede9fe]">
            <textarea
              ref={input}
              rows={1}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={onKeyDown}
              maxLength={2000}
              placeholder={t('Спросите что-нибудь о центре…')}
              aria-label={t('Вопрос ИИ-помощнику')}
              className="max-h-32 min-h-[24px] flex-1 resize-none bg-transparent py-1 text-sm text-ink outline-none placeholder:text-ink-subtle [field-sizing:content]"
            />
            <button type="submit" disabled={busy || loading || !draft.trim()} aria-label={t('Отправить')} className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8b5cf6,#ec4899)] text-white transition hover:brightness-105 disabled:opacity-40">
              <ArrowUp className="size-4" />
            </button>
          </div>
          <p className="mt-1.5 px-1 text-[11px] text-ink-subtle">{t('Чаты сохраняются, их видите только вы. ИИ может ошибаться — важные цифры проверяйте на экранах.')}</p>
        </form>
      </div>
    </Card>
  )
}

export function Thinking() {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-muted">
      <span className="flex gap-1 rounded-2xl rounded-tl-sm bg-surface px-3.5 py-3 shadow-card">
        {[0, 150, 300].map(delay => (
          <span key={delay} className="size-1.5 animate-bounce rounded-full bg-[#a78bfa]" style={{ animationDelay: `${delay}ms` }} />
        ))}
      </span>
      {t('Смотрю данные…')}
    </div>
  )
}

export function Message({ message, onRetry }) {
  if (message.role === 'user') {
    return (
      <div className="flex justify-end" data-question>
        <p className="max-w-[85%] whitespace-pre-line rounded-2xl rounded-tr-sm bg-[linear-gradient(135deg,#8b5cf6,#a855f7)] px-3.5 py-2.5 text-sm text-white shadow-sm">{message.content}</p>
      </div>
    )
  }
  return (
    <div className="flex max-w-[92%] flex-col gap-1.5">
      <div className={cn('rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-sm shadow-card', message.error ? 'bg-danger-50 text-danger-600' : 'bg-surface text-ink')}>
        {message.error ? message.content : <Markdown text={message.content} />}
      </div>
      {message.error && message.retry && (
        <button type="button" onClick={() => onRetry(message.retry)} className="inline-flex items-center gap-1.5 self-start px-1 text-[12px] font-semibold text-ink-muted hover:text-ink">
          <RefreshCw className="size-3.5" /> {t('Повторить')}
        </button>
      )}
      {message.sources?.length > 0 && <Sources sources={message.sources} />}
    </div>
  )
}

export function Sources({ sources }) {
  return (
    <p className="flex items-center gap-1.5 px-1 text-[11px] text-ink-subtle">
      <Eye className="size-3.5" /> {t('Посмотрел: {list}', { list: sources.map(s => t(s)).join(', ') })}
    </p>
  )
}
