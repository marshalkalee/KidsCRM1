import { useSession } from '../../session/SessionContext'
import { useAI } from './ai'

/**
 * Доступен ли чат с ИИ этому сотруднику: роль и ключ ИИ на сервере.
 * null — ещё неизвестно (статус ИИ грузится).
 */
export function useAIChatAvailable() {
  const ai = useAI()
  const { can } = useSession()
  if (!can('can_use_ai_chat')) return false
  return ai.loading ? null : ai.enabled
}
