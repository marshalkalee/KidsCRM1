import { useEffect, useState } from 'react'
import { ArrowRight, CalendarDays, Contact, Sparkles, Users, UsersRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import { Button, Card, PageHeader } from '../ui'

// Главная — приветствие, прогресс настройки центра (владельцу, пока не
// завершена) и быстрые переходы. Сводка по деньгам и посещаемости — позже.
const SHORTCUTS = [
  { to: '/children', label: 'Дети', description: 'База, фильтры, карточки', icon: Users },
  { to: '/parents', label: 'Родители', description: 'Контакты, долги, оплаты', icon: Contact },
  { to: '/groups', label: 'Группы', description: 'Состав и заполняемость', icon: UsersRound },
  { to: '/schedule', label: 'Расписание', description: 'Занятия на неделю', icon: CalendarDays },
]

function greeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Доброе утро'
  if (hour < 18) return 'Добрый день'
  return 'Добрый вечер'
}

export default function Dashboard() {
  const { user, can } = useSession()
  const firstName = user?.full_name?.split(/\s+/)[0]
  const isOwner = can('can_manage_org_settings')
  return (
    <>
      <PageHeader title={`${greeting()}${firstName ? `, ${firstName}` : ''}`} description="С чего начнём?" />
      {isOwner && <OnboardingCard />}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {SHORTCUTS.map(item => (
          <Link key={item.to} to={item.to} className="group">
            <Card className="h-full transition-shadow group-hover:shadow-pop">
              <span className="mb-4 flex size-10 items-center justify-center rounded-md bg-brand-50 text-brand-600">
                <item.icon className="size-5" />
              </span>
              <p className="font-bold text-ink">{item.label}</p>
              <p className="mt-0.5 text-sm text-ink-muted">{item.description}</p>
            </Card>
          </Link>
        ))}
      </div>
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
            <p className="text-base font-bold text-ink">Настройка центра {state.done} / {state.total}</p>
            <p className="mt-0.5 text-sm text-ink-muted">{next ? `Следующий шаг — ${next.title.toLowerCase()}.` : 'Осталось подтвердить завершение.'}</p>
            <div className="mt-3 h-1.5 w-56 max-w-full overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full bg-brand-600" style={{ width: `${percent}%` }} />
            </div>
          </div>
        </div>
        <Button to="/onboarding" variant="primary" icon={ArrowRight}>Продолжить</Button>
      </div>
    </Card>
  )
}
