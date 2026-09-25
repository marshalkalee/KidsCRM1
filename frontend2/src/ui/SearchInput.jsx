import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { cn } from './cn'

/**
 * Поле поиска для списков: value живёт в адресе (?q=), а onChange
 * вызывается с задержкой — когда пользователь перестал печатать, а не на
 * каждую букву (каждая буква = запрос на сервер).
 */
export function SearchInput({ value, onChange, placeholder, className, delay = 300 }) {
  const [text, setText] = useState(value)
  const [synced, setSynced] = useState(value)
  if (value !== synced) {
    // Сброс фильтров или «назад» поменяли q снаружи — показываем его.
    setSynced(value)
    setText(value)
  }
  useEffect(() => {
    if (text.trim() === value) return undefined
    const timer = setTimeout(() => onChange(text.trim()), delay)
    return () => clearTimeout(timer)
  }, [text, value, onChange, delay])

  return (
    <label className={cn('flex h-10 items-center gap-2.5 rounded-[10px] border border-line bg-surface px-3.5 focus-within:border-brand-400 focus-within:ring-3 focus-within:ring-brand-50', className)}>
      <Search className="size-4 shrink-0 text-ink-subtle" />
      <input
        type="search"
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full bg-transparent text-[13px] text-ink placeholder:text-ink-subtle focus:outline-none"
      />
    </label>
  )
}
