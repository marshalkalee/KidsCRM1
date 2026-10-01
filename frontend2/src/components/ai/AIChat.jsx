import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowUp, Eye, History, Maximize2, MessageSquarePlus, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { Card, Skeleton, apiErrorMessage, cn, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'
import { useAIChatAvailable } from './useAIChatAvailable'

/*
 * Чат с ИИ (backend: ai/chat.py) — на главной и на странице «ИИ-помощник».
 * ИИ отвечает по живым данным CRM с правами того, кто спрашивает, только
 * читает. Переписка хранится на сервере (видит только автор): открытый
 * чат возвращается и после закрытия вкладки, и на другом устройстве.
 * Какой чат открыт — помнит браузер; «Новый чат» тоже запоминается.
 */

const NEW_CHAT = 'new'

function currentKey(user) {
  return `kc-ai-chat-current:${user?.id || ''}`
}

function readCurrent(user) {
  try {
    return localStorage.getItem(currentKey(user))
  } catch {
    return null
  }
}

function writeCurrent(user, value) {
  try {
    localStorage.setItem(currentKey(user), value || NEW_CHAT)
  } catch {
    // приватное окно — откроется последний чат
  }
}

function suggestions(can) {
  return [
    t('Что сегодня требует внимания?'),
    t('Кто должен больше всех?'),
    t('Чьи абонементы заканчиваются на этой неделе?'),
    can('can_view_analytics') ? t('Выручка за прошлый месяц по филиалам') : t('Какие занятия сегодня?'),
    t('Какие группы заполнены меньше всего?'),
    t('Сколько новых заявок за эту неделю и откуда?'),
  ]
}

function dayLabel(value) {
  const day = new Date(value)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (day.toDateString() === today.toDateString()) return t('Сегодня')
  if (day.toDateString() === yesterday.toDateString()) return t('Вчера')
  return t('Раньше')
}

export default function AIChat({ full = false }) {
  const { can, user } = useSession()
  const available = useAIChatAvailable()
  const toast = useToast()
  const confirm = useConfirm()
  const [conversations, setConversations] = useState(null)
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const scroller = useRef(null)
  const input = useRef(null)

  const startNew = useCallback(() => {
    setCurrentId(null)
    setMessages([])
    writeCurrent(user, NEW_CHAT)
    setHistoryOpen(false)
  }, [user])

  const openConversation = useCallback(async id => {
    setLoading(true)
    setHistoryOpen(false)
    try {
      const { data } = await api.get(`ai/conversations/${id}/`)
      setMessages(data.messages)
      setCurrentId(id)
      writeCurrent(user, id)
    } catch {
      setConversations(list => (list || []).filter(c => c.id !== id))
      startNew()
    } finally {
      setLoading(false)
    }
  }, [user, startNew])

  // Открыть чат, который был открыт в прошлый раз (или самый свежий).
  useEffect(() => {
    if (!available) return
    let alive = true
    api.get('ai/conversations/')
      .then(({ data }) => {
        if (!alive) return
        setConversations(data)
        const saved = readCurrent(user)
        const id = saved === NEW_CHAT ? null : data.some(c => c.id === saved) ? saved : data[0]?.id
        if (id) openConversation(id)
        else setLoading(false)
      })
      .catch(() => { if (alive) { setConversations([]); setLoading(false) } })
    return () => { alive = false }
  }, [available, user, openConversation])

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
    const question = text.trim()
    if (!question || busy) return
    setMessages(m => [...m.filter(x => !x.error), { role: 'user', content: question }])
    setDraft('')
    setBusy(true)
    try {
      const { data } = await api.post('ai/chat/', { message: question, conversation: currentId })
      const { id, title } = data.conversation
      setCurrentId(id)
      writeCurrent(user, id)
      setConversations(list => [{ id, title, updated_at: new Date().toISOString() }, ...(list || []).filter(c => c.id !== id)])
      setMessages(m => [...m, { role: 'assistant', content: data.answer, sources: data.sources }])
    } catch (err) {
      // Вопрос без ответа на сервере не сохранился — убираем его и даём повторить.
      setMessages(m => [...m.slice(0, -1), { role: 'assistant', content: apiErrorMessage(err), error: true, retry: question }])
    } finally {
      setBusy(false)
      input.current?.focus()
    }
  }

  async function remove(conversation) {
    const ok = await confirm({ title: t('Удалить чат?'), message: conversation.title, confirmText: t('Удалить'), danger: true })
    if (!ok) return
    try {
      await api.delete(`ai/conversations/${conversation.id}/`)
      setConversations(list => list.filter(c => c.id !== conversation.id))
      if (conversation.id === currentId) startNew()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  function onKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault()
      send(draft)
    }
  }

  const firstName = user?.full_name?.split(/\s+/)[0]
  const empty = messages.length === 0
  const headerButton = 'inline-flex h-9 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-semibold hover:bg-surface disabled:opacity-50'

  const historyPanel = full && (
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
              <button type="button" onClick={() => openConversation(c.id)} disabled={busy} className={cn('min-w-0 flex-1 truncate px-3 py-2 text-left text-[13.5px]', c.id === currentId ? 'font-semibold text-[#5b21b6]' : 'text-ink')}>
                {c.title}
              </button>
              <button type="button" onClick={() => remove(c)} aria-label={t('Удалить чат')} className="mr-1 rounded-md p-1.5 text-ink-subtle opacity-100 hover:bg-surface hover:text-danger-600 lg:opacity-0 lg:group-hover:opacity-100">
                <Trash2 className="size-3.5" />
              </button>
            </div>
          </Fragment>
        ))
      )}
    </nav>
  )

  return (
    <Card padded={false} className={cn('flex overflow-hidden', full ? 'h-[calc(100dvh-7.5rem)] min-h-[420px]' : 'mb-6 h-[540px] max-h-[75dvh] flex-col')}>
      {historyPanel}
      <div className={cn('min-w-0 flex-1 flex-col', full && historyOpen ? 'hidden lg:flex' : 'flex')}>
        <header className="flex items-center justify-between gap-3 border-b border-line bg-[linear-gradient(120deg,#f5f3ff,#fdf2f8_60%,#fff)] px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            {full && (
              <Link to="/dashboard" aria-label={t('Главная')} className="inline-flex h-9 shrink-0 items-center gap-1 rounded-md border border-line-strong bg-surface px-2.5 text-[13px] font-semibold text-ink hover:border-[#c4b5fd]">
                <ArrowLeft className="size-4" /><span className="hidden sm:inline">{t('Главная')}</span>
              </Link>
            )}
            <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#8b5cf6,#ec4899)] text-white shadow-sm">
              <Sparkles className="size-5" />
            </span>
            <div className="min-w-0">
              <p className="font-bold text-ink">{t('ИИ-помощник')}</p>
              <p className="truncate text-[13px] text-ink-muted">{t('Отвечает по живым данным CRM — видит то же, что и вы')}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {full ? (
              <button type="button" onClick={() => setHistoryOpen(true)} aria-label={t('История')} className={cn(headerButton, 'text-ink-muted hover:text-ink lg:hidden')}>
                <History className="size-4" /><span className="hidden sm:inline">{t('История')}</span>
              </button>
            ) : (
              <>
                {!empty && (
                  <button type="button" onClick={startNew} disabled={busy} aria-label={t('Новый чат')} className={cn(headerButton, 'text-ink-muted hover:text-ink')}>
                    <MessageSquarePlus className="size-4" /><span className="hidden sm:inline">{t('Новый чат')}</span>
                  </button>
                )}
                <Link to="/assistant" aria-label={t('История')} title={t('История и полный экран')} className={cn(headerButton, 'text-[#7c3aed]')}>
                  <Maximize2 className="size-4" /><span className="hidden sm:inline">{t('История')}</span>
                </Link>
              </>
            )}
          </div>
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
                {suggestions(can).map(text => (
                  <button
                    key={text}
                    type="button"
                    onClick={() => send(text)}
                    className="rounded-lg border border-line bg-surface px-3.5 py-2.5 text-left text-sm font-medium text-ink shadow-card transition hover:border-[#c4b5fd] hover:bg-[#faf5ff]"
                  >
                    {text}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => <Message key={i} message={m} onRetry={send} />)
          )}
          {busy && (
            <div className="flex items-center gap-2 text-sm text-ink-muted">
              <span className="flex gap-1 rounded-2xl rounded-tl-sm bg-surface px-3.5 py-3 shadow-card">
                {[0, 150, 300].map(delay => (
                  <span key={delay} className="size-1.5 animate-bounce rounded-full bg-[#a78bfa]" style={{ animationDelay: `${delay}ms` }} />
                ))}
              </span>
              {t('Смотрю данные…')}
            </div>
          )}
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
            <button
              type="submit"
              disabled={busy || loading || !draft.trim()}
              aria-label={t('Отправить')}
              className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8b5cf6,#ec4899)] text-white transition hover:brightness-105 disabled:opacity-40"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
          <p className="mt-1.5 px-1 text-[11px] text-ink-subtle">{t('Чаты сохраняются, их видите только вы. ИИ может ошибаться — важные цифры проверяйте на экранах.')}</p>
        </form>
      </div>
    </Card>
  )
}

function Message({ message, onRetry }) {
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
      {message.sources?.length > 0 && (
        <p className="flex items-center gap-1.5 px-1 text-[11px] text-ink-subtle">
          <Eye className="size-3.5" /> {t('Посмотрел: {list}', { list: message.sources.map(s => t(s)).join(', ') })}
        </p>
      )}
    </div>
  )
}

/*
 * Ответ ИИ — небольшой Markdown: абзацы, списки, **жирный**, ссылки.
 * Ссылки — только на экраны CRM (/children/…), внешние показываются текстом.
 */
const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g

// «389 000 ₸» не разрывается между строк.
const keepNumbers = text => text.replace(/(\d) (?=\d{3}(?!\d))/g, '$1\u00a0').replace(/(\d) ₸/g, '$1\u00a0₸')

function Inline({ text }) {
  return keepNumbers(text).split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part)
    if (link) {
      return link[2].startsWith('/') && !link[2].startsWith('//')
        ? <Link key={i} to={link[2]} className="font-semibold text-[#7c3aed] underline decoration-[#ddd6fe] underline-offset-2 hover:decoration-[#7c3aed]">{link[1]}</Link>
        : <Fragment key={i}>{link[1]}</Fragment>
    }
    return <Fragment key={i}>{part}</Fragment>
  })
}

function Markdown({ text }) {
  const blocks = []
  for (const raw of text.split('\n')) {
    const line = raw.trimEnd()
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    const last = blocks[blocks.length - 1]
    if (bullet || numbered) {
      const kind = bullet ? 'ul' : 'ol'
      const item = (bullet || numbered)[1]
      if (last?.kind === kind) last.items.push(item)
      else blocks.push({ kind, items: [item] })
    } else if (/^#{1,4}\s+/.test(line)) {
      blocks.push({ kind: 'h', text: line.replace(/^#{1,4}\s+/, '') })
    } else if (line.trim()) {
      if (last?.kind === 'p') last.lines.push(line)
      else blocks.push({ kind: 'p', lines: [line] })
    } else {
      blocks.push({ kind: 'gap' })
    }
  }
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((b, i) => {
        if (b.kind === 'gap') return null
        if (b.kind === 'h') return <p key={i} className="font-bold"><Inline text={b.text} /></p>
        if (b.kind === 'p') return <p key={i}>{b.lines.map((l, j) => <Fragment key={j}>{j > 0 && <br />}<Inline text={l} /></Fragment>)}</p>
        const List = b.kind
        return (
          <List key={i} className={cn('space-y-1 pl-5', b.kind === 'ul' ? 'list-disc marker:text-[#a78bfa]' : 'list-decimal marker:font-semibold marker:text-ink-muted')}>
            {b.items.map((item, j) => <li key={j}><Inline text={item} /></li>)}
          </List>
        )
      })}
    </div>
  )
}
