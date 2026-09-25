import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { CheckCircle2, AlertTriangle, X } from 'lucide-react'
import { cn } from './cn'

const ToastContext = createContext(null)
let nextId = 1

/**
 * const toast = useToast(); toast.success('Сохранено'); toast.error('Не удалось…')
 * Уведомление само исчезает через 4 с (ошибки — через 7 с).
 */
export function ToastProvider({ children }) {
  const [items, setItems] = useState([])
  const dismiss = useCallback(id => setItems(list => list.filter(t => t.id !== id)), [])
  const push = useCallback((tone, text) => {
    const id = nextId++
    setItems(list => [...list, { id, tone, text }])
    setTimeout(() => dismiss(id), tone === 'error' ? 7000 : 4000)
  }, [dismiss])
  const api = useMemo(() => ({
    success: text => push('success', text),
    error: text => push('error', text),
  }), [push])

  return (
    <ToastContext.Provider value={api}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-auto sm:left-auto sm:right-4 sm:top-4 sm:items-end">
          {items.map(item => {
            const Icon = item.tone === 'error' ? AlertTriangle : CheckCircle2
            return (
              <div
                key={item.id}
                role={item.tone === 'error' ? 'alert' : 'status'}
                className={cn(
                  'pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border bg-surface px-4 py-3 text-sm shadow-pop',
                  item.tone === 'error' ? 'border-danger-50 text-danger-600' : 'border-success-50 text-ink',
                )}
              >
                <Icon className={cn('mt-0.5 size-4 shrink-0', item.tone === 'error' ? 'text-danger-600' : 'text-success-600')} />
                <span className="flex-1">{item.text}</span>
                <button type="button" onClick={() => dismiss(item.id)} className="text-ink-subtle hover:text-ink" aria-label="Закрыть">
                  <X className="size-4" />
                </button>
              </div>
            )
          })}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}

/** Текст ошибки для пользователя из ответа DRF (detail / non_field_errors / первая ошибка поля). */
export function apiErrorMessage(error, fallback = 'Что-то пошло не так. Попробуйте ещё раз.') {
  const data = error?.response?.data
  if (!data) return error?.response ? fallback : 'Нет связи с сервером.'
  if (typeof data === 'string') return fallback
  if (data.detail) return data.detail
  if (data.non_field_errors) return data.non_field_errors[0]
  const first = Object.values(data)[0]
  return Array.isArray(first) ? first[0] : fallback
}
