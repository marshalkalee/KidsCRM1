import { useState } from 'react'

/**
 * Черновик фильтров: правки в панели не применяются, пока не нажали
 * «Применить». applied — применённые (из адреса), onApply(values) — записать.
 */
export function useFilterDraft(applied) {
  const key = JSON.stringify(applied)
  const [draft, setDraft] = useState(applied)
  const [syncedKey, setSyncedKey] = useState(key)
  if (key !== syncedKey) {
    // Применённые поменялись снаружи (сброс, «назад») — черновик за ними.
    setSyncedKey(key)
    setDraft(applied)
  }
  return {
    draft,
    set: (name, value) => setDraft(d => ({ ...d, [name]: value })),
    dirty: JSON.stringify(draft) !== key,
  }
}
