import { CalendarDays, Users, UsersRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useSession } from '../session/SessionContext'
import { Card, PageHeader } from '../ui'

// Главная — пока приветствие и быстрые переходы. Прогресс настройки центра
// и сводка появятся в TRU-86.
const SHORTCUTS = [
  { to: '/children', label: 'Дети', description: 'База, фильтры, карточки', icon: Users },
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
  const { user } = useSession()
  const firstName = user?.full_name?.split(/\s+/)[0]
  return (
    <>
      <PageHeader title={`${greeting()}${firstName ? `, ${firstName}` : ''}`} description="С чего начнём?" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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
