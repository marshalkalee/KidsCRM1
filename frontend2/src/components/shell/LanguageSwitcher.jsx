import { useEffect, useRef, useState } from 'react'
import { Check, Globe } from 'lucide-react'
import { LANGUAGES, lang, setLang, t } from '../../i18n'
import { cn } from '../../ui'

/** Переключатель языка RU / KK / EN (TRU-92): иконка в шапке, язык меняется без перезагрузки. */
export default function LanguageSwitcher({ className }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const current = LANGUAGES.find(l => l.code === lang)

  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  return (
    <div className={cn('relative', className)} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="flex size-10 items-center justify-center rounded-[10px] border border-line bg-surface text-ink-muted hover:border-brand-300 hover:text-ink"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t('Язык: {name}', { name: current.label })}
        title={t('Язык: {name}', { name: current.label })}
      >
        <Globe className="size-[18px]" />
      </button>
      {open && (
        <ul role="listbox" className="absolute right-0 top-12 z-40 w-44 overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-pop">
          {LANGUAGES.map(language => (
            <li key={language.code}>
              <button
                type="button"
                role="option"
                aria-selected={language.code === lang}
                onClick={() => { setOpen(false); setLang(language.code) }}
                className={cn(
                  'flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm',
                  language.code === lang ? 'bg-brand-50 font-semibold text-brand-600' : 'text-ink hover:bg-surface-muted',
                )}
              >
                <span><span className="mr-2 text-xs text-ink-subtle">{language.short}</span>{language.label}</span>
                {language.code === lang && <Check className="size-3.5" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
