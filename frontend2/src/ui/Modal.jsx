import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { Button } from './Button'
import { cn } from './cn'

// Ширины — как у модалок первого React: 480 / 520 / 560, большая — для отчётов.
const SIZES = { sm: 'max-w-[480px]', md: 'max-w-[520px]', lg: 'max-w-[560px]', xl: 'max-w-4xl' }

/**
 * Модалка: портал в body, закрытие по Esc и по клику на фон, блокировка
 * прокрутки страницы. На телефоне — выезжает снизу на всю ширину.
 * footer — кнопки действий (обычно Отмена + Сохранить).
 */
export function Modal({ open, onClose, title, description, size = 'md', footer, children }) {
  const panelRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const onKey = e => { if (e.key === 'Escape') onClose?.() }
    document.addEventListener('keydown', onKey)
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    panelRef.current?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [open, onClose])

  if (!open) return null
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/45 p-0 sm:items-center sm:p-6" onMouseDown={e => { if (e.target === e.currentTarget) onClose?.() }}>
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={cn('flex max-h-[92vh] w-full flex-col rounded-t-2xl bg-surface shadow-pop outline-none sm:rounded-2xl', SIZES[size])}
      >
        <div className="flex items-start justify-between gap-4 px-6 pb-1 pt-6">
          <div>
            <h2 className="font-btn text-[17px] font-bold text-ink">{title}</h2>
            {description && <p className="mt-0.5 text-[13px] text-ink-muted">{description}</p>}
          </div>
          <button type="button" onClick={onClose} className="-mr-1 rounded-md p-1 text-ink-subtle hover:bg-surface-muted hover:text-ink" aria-label="Закрыть">
            <X className="size-5" />
          </button>
        </div>
        <div className="overflow-y-auto px-6 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-6 pb-5 pt-1">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

const ConfirmContext = createContext(null)

/**
 * const confirm = useConfirm()
 * if (await confirm({ title: 'Удалить?', confirmText: 'Удалить', danger: true })) …
 */
export function ConfirmProvider({ children }) {
  const [state, setState] = useState(null)
  const confirm = useCallback(
    options => new Promise(resolve => setState({ ...options, resolve })),
    [],
  )
  const close = result => {
    state?.resolve(result)
    setState(null)
  }
  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Modal
        open={Boolean(state)}
        onClose={() => close(false)}
        title={state?.title}
        size="sm"
        footer={
          <>
            <Button onClick={() => close(false)}>{state?.cancelText || 'Отмена'}</Button>
            <Button variant={state?.danger ? 'danger' : 'primary'} onClick={() => close(true)}>
              {state?.confirmText || 'Подтвердить'}
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-muted">{state?.message}</p>
      </Modal>
    </ConfirmContext.Provider>
  )
}

export function useConfirm() {
  return useContext(ConfirmContext)
}
