import { useEffect, useState } from 'react'
import { ArrowRight, Sparkles } from 'lucide-react'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import { Button, Card, Skeleton } from '../ui'
import { t } from '../i18n'
import { useAIChatAvailable } from '../components/ai/useAIChatAvailable'
import { AIHeader, DashboardHeader } from '../components/dashboard/DashboardHeader'
import { Attention, Birthdays, KpiTiles, Renewals, TodayLessons } from '../components/dashboard/DashboardBlocks'
import { useDashboardData } from '../components/dashboard/useDashboardData'

/*
 * Главная — «как центр сегодня» (пробник 01.10.2026: шапка из варианта B,
 * остальное из A). Сверху вопрос к ИИ (у кого есть чат) или дата и быстрые
 * действия; дальше ключевые цифры за 30 дней, что требует внимания,
 * продления, дни рождения и занятия на сегодня. Набор блоков — по правам
 * роли: выручка — руководителям, деньги — тем, кто их видит, педагогу —
 * его занятия.
 */
export default function Dashboard() {
  const { can, user } = useSession()
  const chatAvailable = useAIChatAvailable()
  const data = useDashboardData()
  const block = key => (data ? data[key] : null)
  return (
    <>
      {can('can_manage_org_settings') && <OnboardingCard />}
      {chatAvailable === null ? <Skeleton className="mb-5 h-56" /> : chatAvailable ? <AIHeader /> : <DashboardHeader />}
      <KpiTiles data={data} />
      <div className="mb-5 grid gap-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <Attention items={block('attention')} />
        <div className="flex flex-col gap-4">
          <Renewals data={block('renewals')} />
          <Birthdays rows={block('birthdays')} />
        </div>
      </div>
      <TodayLessons lessons={block('lessons')} mine={user?.role === 'teacher'} />
    </>
  )
}

/** «Настройка центра N / 6» — пока владелец не завершил мастер. */
function OnboardingCard() {
  const [state, setState] = useState(null)
  useEffect(() => {
    api.get('onboarding/').then(r => setState(r.data)).catch(() => {})
  }, [])
  if (!state || state.finished || state.done === state.total) return null
  const percent = Math.round((state.done / state.total) * 100)
  const next = state.steps.find(s => s.status === 'todo') || state.steps.find(s => s.status !== 'done')
  return (
    <Card className="mb-6 overflow-hidden border-brand-100 bg-gradient-to-br from-brand-50 to-surface">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-4">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-brand-600 text-white"><Sparkles className="size-5" /></span>
          <div>
            <p className="text-base font-bold text-ink">{t('Настройка центра')} {state.done} / {state.total}</p>
            <p className="mt-0.5 text-sm text-ink-muted">{next ? t('Следующий шаг — {step}.', { step: t(next.title).toLowerCase() }) : t('Осталось подтвердить завершение.')}</p>
            <div className="mt-3 h-1.5 w-56 max-w-full overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full bg-brand-600" style={{ width: `${percent}%` }} />
            </div>
          </div>
        </div>
        <Button to="/onboarding" variant="primary" icon={ArrowRight}>{t('Продолжить')}</Button>
      </div>
    </Card>
  )
}
