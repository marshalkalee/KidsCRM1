# frontend2 — веб KidsCRM (React)

React 19 + Vite + Tailwind v4 + react-router. Ходит только в REST API
`/api/v1/` с JWT — см. [ADR-004](../backend/docs/adr-004-frontend-spa.md).
Запуск и сборка — в корневом [README](../README.md#фронтенд-frontend2).

## Как устроено

| Где | Что |
|---|---|
| `src/api/axios.js` | Общий клиент API: токен, продление по refresh при 401, заголовок активного филиала `X-Branch-Id`. Запросы — `api.get('clients/…')`. |
| `src/session/SessionContext.jsx` | Кто вошёл: `useSession()` → `user`, `can('can_manage_branches')`, `roleLabel`, филиалы и активный филиал, `logout()`. `RequireAuth`, `RequirePermission`. |
| `src/components/shell/` | Каркас: меню (`navigation.js` — пункты и права), шапка, поиск (Ctrl+K), переключатель филиала. |
| `src/ui/` | Общие компоненты — экраны собираются из них. |
| `src/pages/` | Экраны. |

## Правила

- **Цвета и размеры — только токены** из `src/index.css` (`bg-surface`,
  `text-ink-muted`, `bg-brand-600`, `border-line` …), не hex-коды и не
  inline-`style`. Новый оттенок — сначала токен.
- **Компоненты из `src/ui`**, а не своя разметка кнопок, полей, таблиц и
  модалок: `Button`, `Field` + `Input`/`Select`/`Textarea`/`Checkbox`,
  `Card`, `Badge`, `PageHeader`, `DataTable` (десктоп — таблица, телефон —
  карточки, серверные сортировка и пагинация), `Modal`, `useConfirm()`,
  `useToast()` + `apiErrorMessage(error)`, `EmptyState`, `ErrorState`,
  `Spinner`, `Skeleton`, `plural(n, ['ребёнок', 'ребёнка', 'детей'])`.
- **Права:** скрывать пункты и кнопки по `can(...)` — удобство, а не
  защита. Проверка обязательно на API.
- **Новый экран в меню** — только когда он реально есть (`navigation.js`).
  Никаких ссылок в никуда.
- **Телефон:** каждый экран проверяется на ширине 390px, без
  горизонтального скролла (ТЗ п. 10.4).
- `npm run lint` (oxlint) и `npm run build` должны проходить — это
  проверяет CI.
