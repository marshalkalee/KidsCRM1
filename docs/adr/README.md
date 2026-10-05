# Архитектурные решения (ADR)

Формат: `NNNN-kebab-slug.md`, номер — сквозной по всему репозиторию (не по
домену). Шаблон — [`0000-template.md`](0000-template.md), тот же, что
использован в ADR-001/ADR-002.

## Реестр

| № | Название | Статус |
|---|---|---|
| 0001 | Модель мультитенантности | [`0001-multitenancy.md`](0001-multitenancy.md) |
| 0002 | Стек, структура репозитория и формат API | [`0002-stack-repo-api.md`](0002-stack-repo-api.md); раздел «Frontend» заменён ADR-004 |
| 0003 | Абстракция провайдера оплаты | [`0003-payment-provider-abstraction.md`](0003-payment-provider-abstraction.md) |
| 0004 | Фронтенд — React SPA (frontend2) поверх REST API | [`0004-frontend-spa.md`](0004-frontend-spa.md) — принято |
| 0005 | Ребёнок-кандидат для пробного занятия | [`0005-trial-candidate-child.md`](0005-trial-candidate-child.md) — предложено в TRU-100, требуется ревью Анель |
| 0006 | Аналитика: считать на лету с кэшем, снимки для истории | [`0006-analytics-aggregates.md`](0006-analytics-aggregates.md) — TRU-118 |
| 0007 | Код входа родителя: каналы и провайдеры для Казахстана | [`0007-otp-provider.md`](0007-otp-provider.md) — предложено, TRU-134 |

ADR-001…004 до 05.10.2026 лежали в `backend/docs/` (до соглашения о единой
папке); перенесены сюда в TRU-151 без изменения содержания. Новые ADR — только
в `docs/adr/`.
