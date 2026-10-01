import { Fragment, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUp, Eye, Maximize2, RefreshCw, RotateCcw, Sparkles } from 'lucide-react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { Card, apiErrorMessage, cn } from '../../ui'
import { t } from '../../i18n'
import { useAIChatAvailable } from './useAIChatAvailable'

/*
 * Чат с ИИ (backend: ai/chat.py) — на главной и на странице «ИИ-помощник».
 * ИИ отвечает по живым данным CRM с правами того, кто спрашивает, только
 * читает. Переписка живёт в sessionStorage: переход между главной и
 * полной версией её не теряет, закрытая вкладка — забывает.
 */

const STORAGE_KEY = 'kc-ai-chat'
const HISTORY_SENT = 20

function loadMessages() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '[]')
    return Array.isArray(saved) ? saved : []
  } catch {
    return []
  }
}

function saveMessages(messages) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-40)))
  } catch {
    // приватное окно / нет места — чат просто не переживёт переход
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

export default function AIChat({ full = false }) {
  const { can, user } = useSession()
  const available = useAIChatAvailable()
  const [messages, setMessages] = useState(loadMessages)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const scroller = useRef(null)
  const input = useRef(null)

  useEffect(() => { saveMessages(messages) }, [messages])
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
    box.scrollTo({ top, behavior: 'smooth' })
  }, [messages, busy])

  if (!available) return null

  async function send(text) {
    const question = text.trim()
    if (!question || busy) return
    const history = [...messages.filter(m => !m.error), { role: 'user', content: question }]
    setMessages(history)
    setDraft('')
    setBusy(true)
    try {
      const { data } = await api.post('ai/chat/', {
        messages: history.slice(-HISTORY_SENT).map(({ role, content }) => ({ role, content })),
      })
      setMessages(m => [...m, { role: 'assistant', content: data.answer, sources: data.sources }])
    } catch (err) {
      setMessages(m => [...m, { role: 'assistant', content: apiErrorMessage(err), error: true, retry: question }])
    } finally {
      setBusy(false)
      input.current?.focus()
    }
  }

  function retry(question) {
    setMessages(m => {
      const trimmed = m.slice(0, -1)
      return trimmed[trimmed.length - 1]?.content === question ? trimmed.slice(0, -1) : trimmed
    })
    send(question)
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
    <Card padded={false} className={cn('flex flex-col overflow-hidden', full ? 'h-[calc(100dvh-7.5rem)] min-h-[420px]' : 'mb-6 h-[540px] max-h-[75dvh]')}>
      <header className="flex items-center justify-between gap-3 border-b border-line bg-[linear-gradient(120deg,#f5f3ff,#fdf2f8_60%,#fff)] px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#8b5cf6,#ec4899)] text-white shadow-sm">
            <Sparkles className="size-5" />
          </span>
          <div className="min-w-0">
            <p className="font-bold text-ink">{t('ИИ-помощник')}</p>
            <p className="truncate text-[13px] text-ink-muted">{t('Отвечает по живым данным CRM — видит то же, что и вы')}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {!empty && (
            <button type="button" onClick={() => setMessages([])} disabled={busy} className="inline-flex h-9 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-semibold text-ink-muted hover:bg-surface hover:text-ink disabled:opacity-50" title={t('Новый чат')}>
              <RotateCcw className="size-4" /><span className="hidden sm:inline">{t('Новый чат')}</span>
            </button>
          )}
          {!full && (
            <Link to="/assistant" className="inline-flex h-9 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-semibold text-[#7c3aed] hover:bg-surface" title={t('Открыть на весь экран')}>
              <Maximize2 className="size-4" /><span className="hidden sm:inline">{t('На весь экран')}</span>
            </Link>
          )}
        </div>
      </header>

      <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto bg-canvas/40 px-4 py-4 sm:px-5" aria-live="polite">
        {empty ? (
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
          messages.map((m, i) => <Message key={i} message={m} onRetry={retry} />)
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
            disabled={busy || !draft.trim()}
            aria-label={t('Отправить')}
            className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[linear-gradient(135deg,#8b5cf6,#ec4899)] text-white transition hover:brightness-105 disabled:opacity-40"
          >
            <ArrowUp className="size-4" />
          </button>
        </div>
        <p className="mt-1.5 px-1 text-[11px] text-ink-subtle">{t('ИИ может ошибаться — важные цифры проверяйте на экранах. Телефоны и почта в ИИ не передаются.')}</p>
      </form>
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
