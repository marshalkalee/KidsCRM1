import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, User, Users } from 'lucide-react'
import api from '../../api/axios'
import { cn } from '../../ui'
import { t } from '../../i18n'

const MIN_LENGTH = 3 // как на сервере (search.GLOBAL_SEARCH_MIN_LENGTH)
const DEBOUNCE_MS = 250

const MATCHED_ON = {
  child_name: null,
  parent_name: t('родитель'),
  phone: t('телефон'),
}

function resultUrl(result) {
  return result.type === 'child' ? `/children/${result.id}` : `/parents/${result.id}`
}

/**
 * Поиск по детям, родителям и телефону с любого экрана (ТЗ п. 4.1, TRU-80):
 * одно поле, задержка ввода, устаревший запрос отменяется (AbortController),
 * навигация стрелками + Enter, Ctrl/⌘+K — перейти в поле.
 */
export function GlobalSearch({ className }) {
  const navigate = useNavigate()
  const inputRef = useRef(null)
  const [query, setQuery] = useState('')
  // Результаты вместе с запросом, для которого они пришли: пока ответ на
  // новый запрос не пришёл, показываем «Ищем…», а не «ничего не нашлось».
  const [found, setFound] = useState({ q: '', results: [] })
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)

  useEffect(() => {
    const onKey = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const q = query.trim()
  const tooShort = q.length < MIN_LENGTH
  const loading = !tooShort && found.q !== q
  const results = tooShort || loading ? [] : found.results
  const showPanel = open && !tooShort

  useEffect(() => {
    if (tooShort) return undefined
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api.get('clients/search/', { params: { q }, signal: controller.signal })
        .then(res => { setFound({ q, results: res.data.results }); setActive(0) })
        .catch(() => {})
    }, DEBOUNCE_MS)
    return () => { clearTimeout(timer); controller.abort() }
  }, [q, tooShort])

  function go(result) {
    setOpen(false)
    setQuery('')
    inputRef.current?.blur()
    navigate(resultUrl(result))
  }

  function onKeyDown(e) {
    if (tooShort || !results.length) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(i => (i + 1) % results.length) }
    if (e.key === 'ArrowUp') { e.preventDefault(); setActive(i => (i - 1 + results.length) % results.length) }
    if (e.key === 'Enter') { e.preventDefault(); go(results[active]) }
    if (e.key === 'Escape') inputRef.current?.blur()
  }


  return (
    <div className={cn('relative', className)}>
      <div className="flex h-10 items-center gap-2 rounded-[10px] border border-line bg-surface-muted px-3 focus-within:border-brand-400 focus-within:bg-surface focus-within:ring-3 focus-within:ring-brand-100">
        <Search className="size-4 shrink-0 text-ink-subtle" />
        <input
          ref={inputRef}
          value={query}
          onChange={e => setQuery(e.target.value)}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKeyDown}
          placeholder={t('Ребёнок, родитель или телефон')}
          className="w-full bg-transparent text-sm text-ink placeholder:text-ink-subtle focus:outline-none"
          aria-label={t('Поиск')}
          role="combobox"
          aria-expanded={showPanel}
        />
      </div>

      {showPanel && (
        <div className="absolute left-0 right-0 top-12 z-40 overflow-hidden rounded-lg border border-line bg-surface shadow-pop" role="listbox">
          {loading && <p className="px-4 py-3 text-sm text-ink-muted">{t('Ищем…')}</p>}
          {!loading && !results.length && <p className="px-4 py-3 text-sm text-ink-muted">{t('Ничего не нашлось')}</p>}
          {results.map((result, i) => {
            const Icon = result.type === 'child' ? User : Users
            const hint = MATCHED_ON[result.matched_on]
            return (
              <button
                key={`${result.type}-${result.id}`}
                type="button"
                role="option"
                aria-selected={i === active}
                onMouseDown={e => e.preventDefault()}
                onClick={() => go(result)}
                onMouseEnter={() => setActive(i)}
                className={cn('flex w-full items-center gap-3 px-4 py-2.5 text-left', i === active && 'bg-surface-muted')}
              >
                <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full', result.type === 'child' ? 'bg-brand-50 text-brand-600' : 'bg-info-50 text-info-600')}>
                  <Icon className="size-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-ink">{result.title}</span>
                  <span className="block truncate text-xs text-ink-muted">
                    {result.type === 'child' ? t('Ребёнок') : t('Родитель')}
                    {hint && result.matched_detail ? ` · ${hint}: ${result.matched_detail}` : ''}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
