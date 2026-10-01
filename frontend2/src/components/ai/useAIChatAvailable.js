import { useSession } from '../../session/SessionContext'
import { useAI } from './ai'

/** Доступен ли чат с ИИ этому сотруднику: роль и ключ ИИ на сервере. */
export function useAIChatAvailable() {
  const ai = useAI()
  const { can } = useSession()
  return ai.enabled && can('can_use_ai_chat')
}
