import { Loader2, Mic, Paperclip, Pause, Send, Square, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cn, useToast } from '../../ui'
import { t } from '../../i18n'
import { VOICE_SUPPORTED, useVoiceRecorder } from './voiceRecorder'

/*
 * Поле ввода чата — общее для CRM (чат WhatsApp) и кабинета родителя (чат с
 * центром): скрепка, поле, растущее с текстом, голосовое с паузой и
 * прослушиванием перед отправкой. Как в мессенджере: пока поле пустое —
 * микрофон, когда есть текст или файл — «Отправить».
 *
 * onSend({ text, file }) — Promise; ошибку показывает вызывающий код и
 * пробрасывает её, тогда введённое не стирается.
 */
const ACCEPT = 'image/*,audio/*,video/mp4,.pdf,.doc,.docx,.xls,.xlsx,.txt,.csv'

const iconButton = 'flex size-11 shrink-0 items-center justify-center rounded-xl transition'
const primaryButton = cn(iconButton, 'bg-brand-gradient text-white shadow-brand hover:brightness-105 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none')

export default function ChatComposer({ onSend, placeholder }) {
  const toast = useToast()
  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [sending, setSending] = useState(false)
  const input = useRef(null)

  const voice = useVoiceRecorder({
    onRecorded: recorded => submit({ text: '', file: recorded }, false),
    onError: reason => toast.error(reason === 'silent'
      ? t('Микрофон не передаёт звук — голосовое не отправлено. Проверьте, какой микрофон выбран в браузере и в Windows и не выключен ли он.')
      : t('Нет доступа к микрофону. Разрешите его в настройках браузера.')),
  })

  // Поле растёт вместе с текстом (до ~6 строк), потом прокручивается.
  useEffect(() => {
    const field = input.current
    if (!field) return
    field.style.height = 'auto'
    field.style.height = `${Math.min(field.scrollHeight, 144)}px`
  }, [text])

  // clearDraft — голосовое уходит само по себе, набранный текст не трогаем.
  async function submit(payload, clearDraft = true) {
    setSending(true)
    try {
      await onSend(payload)
      if (clearDraft) {
        setText('')
        setFile(null)
      }
    } catch {
      // Ошибку уже показали; черновик остаётся, чтобы отправить ещё раз.
    } finally {
      setSending(false)
    }
  }

  const canSend = Boolean(text.trim() || file) && !sending
  return (
    <div>
      {file && (
        <span className="mb-2 inline-flex max-w-full items-center gap-1.5 rounded-lg bg-brand-50 px-2.5 py-1.5 text-xs font-medium text-brand-700">
          <Paperclip className="size-3.5 shrink-0" />
          <span className="truncate">{file.name}</span>
          <button type="button" aria-label={t('Убрать файл')} onClick={() => setFile(null)} className="rounded text-brand-600 hover:text-brand-800">
            <X className="size-3.5" />
          </button>
        </span>
      )}
      {voice.preview ? (
        // Прослушать перед отправкой: удалить или отправить.
        <div className="flex items-center gap-1.5 rounded-2xl border border-brand-300 bg-brand-50 p-1.5">
          <button type="button" onClick={voice.discard} aria-label={t('Удалить запись')} title={t('Удалить запись')} className={cn(iconButton, 'text-danger-600 hover:bg-surface')}>
            <Trash2 className="size-5" />
          </button>
          <audio controls src={voice.preview.url} className="h-11 min-w-0 flex-1" />
          <button type="button" onClick={voice.send} disabled={sending} aria-label={t('Отправить голосовое')} title={t('Отправить голосовое')} className={primaryButton}>
            {sending ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
          </button>
        </div>
      ) : voice.recording ? (
        <div className="flex items-center gap-1.5 rounded-2xl border border-danger-600/30 bg-danger-50 p-1.5">
          <button type="button" onClick={voice.cancel} aria-label={t('Отменить запись')} title={t('Отменить запись')} className={cn(iconButton, 'text-danger-600 hover:bg-surface')}>
            <Trash2 className="size-5" />
          </button>
          <span className="flex min-w-0 flex-1 items-center gap-2 px-1.5 text-sm font-semibold text-ink">
            <span className={cn('size-2.5 shrink-0 rounded-full bg-danger-600', !voice.paused && 'animate-pulse')} />
            <span className="truncate">{voice.paused ? t('Пауза') : t('Идёт запись')}</span>
            <span className="tabular-nums">{Math.floor(voice.seconds / 60)}:{String(voice.seconds % 60).padStart(2, '0')}</span>
            {/* Уровень звука: полоски двигаются, когда микрофон слышит голос. */}
            {!voice.paused && (
              <span className="ml-1 flex h-5 items-center gap-0.5" aria-hidden>
                {[0.15, 0.35, 0.6, 0.85, 1].map(step => (
                  <span
                    key={step}
                    className={cn('w-1 rounded-full transition-all', voice.level >= step * 0.6 ? 'bg-danger-600' : 'bg-danger-600/20')}
                    style={{ height: `${6 + step * 14}px` }}
                  />
                ))}
              </span>
            )}
          </span>
          <button
            type="button"
            onClick={voice.paused ? voice.resume : voice.pause}
            aria-label={voice.paused ? t('Продолжить запись') : t('Пауза')}
            title={voice.paused ? t('Продолжить запись') : t('Пауза')}
            className={cn(iconButton, 'text-danger-600 hover:bg-surface')}
          >
            {voice.paused ? <Mic className="size-5" /> : <Pause className="size-5" />}
          </button>
          <button type="button" onClick={voice.finish} aria-label={t('Остановить и прослушать')} title={t('Остановить и прослушать')} className={primaryButton}>
            <Square className="size-4 fill-current" />
          </button>
        </div>
      ) : (
        <div className="flex items-end gap-1.5 rounded-2xl border border-line bg-surface-muted p-1.5 transition-colors focus-within:border-brand-300 focus-within:bg-surface">
          <label className={cn(iconButton, 'cursor-pointer text-ink-muted hover:bg-brand-50 hover:text-brand-600')} title={t('Прикрепить файл')} aria-label={t('Прикрепить файл')}>
            <Paperclip className="size-5" />
            <input type="file" accept={ACCEPT} className="sr-only" onChange={event => { setFile(event.target.files?.[0] || null); event.target.value = '' }} />
          </label>
          <textarea
            ref={input}
            rows={1}
            maxLength={4096}
            value={text}
            placeholder={file ? t('Подпись к файлу') : placeholder}
            aria-label={placeholder}
            onChange={event => setText(event.target.value)}
            onKeyDown={event => {
              // Enter — отправить, Shift + Enter — новая строка.
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                if (canSend) submit({ text, file })
              }
            }}
            className="max-h-36 min-h-11 min-w-0 flex-1 resize-none border-0 bg-transparent px-1.5 py-[11px] text-sm leading-[22px] text-ink outline-none placeholder:text-ink-subtle focus:ring-0"
          />
          {!text.trim() && !file && VOICE_SUPPORTED && !sending ? (
            <button type="button" onClick={voice.start} aria-label={t('Записать голосовое')} title={t('Записать голосовое')} className={primaryButton}>
              <Mic className="size-5" />
            </button>
          ) : (
            <button type="button" onClick={() => submit({ text, file })} disabled={!canSend} aria-label={t('Отправить')} title={t('Отправить')} className={primaryButton}>
              {sending ? <Loader2 className="size-5 animate-spin" /> : <Send className="size-5" />}
            </button>
          )}
        </div>
      )}
      <p className="mt-1.5 px-1 text-[11px] text-ink-subtle">{t('Enter — отправить, Shift + Enter — новая строка')}</p>
    </div>
  )
}
