import { Sparkles } from 'lucide-react'
import AIChat from '../components/ai/AIChat'
import { useAI } from '../components/ai/ai'
import { useAIChatAvailable } from '../components/ai/useAIChatAvailable'
import { Card, EmptyState } from '../ui'
import { t } from '../i18n'

/** ИИ-помощник на весь экран — тот же чат, что на главной; заголовок — в шапке чата. */
export default function Assistant() {
  const ai = useAI()
  const available = useAIChatAvailable()
  if (available) return <AIChat full />
  return (
    <Card>
      <EmptyState icon={Sparkles} title={ai.enabled === false ? t('ИИ-помощник не подключён') : t('Загрузка…')} />
    </Card>
  )
}
