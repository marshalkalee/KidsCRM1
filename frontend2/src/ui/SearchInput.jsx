import { useEffect, useState } from 'react'
import { Search } from 'lucide-react'
import { Input } from './Field'
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
    <div className={cn('relative', className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-subtle" />
      <Input type="search" value={text} onChange={e => setText(e.target.value)} placeholder={placeholder} aria-label={placeholder} className="pl-9" />
    </div>
  )
}
