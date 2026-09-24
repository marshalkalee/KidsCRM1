import { useParams } from 'react-router-dom'
import { ExternalLink, Users } from 'lucide-react'
import { Button, Card, EmptyState } from '../ui'

// Временная страница: карточка родителя ещё не перенесена во frontend2
// (TRU-83). Поиск в шапке уже находит родителей — ведём в старую карточку,
// а не в «страница не найдена». Удалить вместе с переносом TRU-83.
export default function ParentPlaceholder() {
  const { id } = useParams()
  return (
    <Card>
      <EmptyState
        icon={Users}
        title="Карточка родителя переезжает в новый интерфейс"
        description="Пока её можно открыть в прежнем интерфейсе — там все данные и действия."
        action={
          <Button variant="primary" icon={ExternalLink} onClick={() => window.location.assign(`/clients/parents/${id}/`)}>
            Открыть карточку
          </Button>
        }
      />
    </Card>
  )
}
