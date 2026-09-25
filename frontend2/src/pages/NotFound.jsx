import { Compass } from 'lucide-react'
import { Button, EmptyState } from '../ui'

export default function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Страница не найдена"
      description="Возможно, ссылка устарела или раздел ещё переезжает в новый интерфейс."
      action={<Button variant="primary" to="/dashboard">На главную</Button>}
    />
  )
}
