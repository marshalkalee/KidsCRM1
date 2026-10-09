"""
Корневой urlconf. Публичный REST API живёт под /api/v1/ (версионирование
через URL-префикс) — на него ходит веб frontend2 (React, ADR-004).
Серверные Django-страницы удалены в TRU-88. Каждый домен подключает
свои urls.py отдельным include(), чтобы домены не правили один и тот же
файл маршрутов.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

api_v1_patterns = [
    # Organization (только текущая, /organization/), Branch, Room.
    path("", include("domains.platform.tenants.urls")),
    path("users/", include("domains.platform.users.urls")),
    path("clients/", include("domains.people.clients.urls")),
    # Отдельно от clients/ — так уже ждёт фронт (frontend2/ChildDetail.jsx),
    # не переименовываем под него (ТЗ п. 3.1, п. 4.1; запись обзвона о
    # переносе занятия — TRU-49, LessonViewSet.mark_called).
    path("communications/", include("domains.people.clients.communications_urls")),
    path("schedule/", include("domains.scheduling.schedule.urls")),
    path("groups/", include("domains.scheduling.groups.urls")),
    path("schedule-templates/", include("domains.scheduling.schedule_templates.urls")),
    path("attendance/", include("domains.scheduling.attendance.urls")),
    path("subscriptions/", include("domains.money.subscriptions.urls")),
    path("payments/", include("domains.money.payments.urls")),
    path("notifications/", include("domains.platform.notifications.urls")),
    # Центр рассылок родителям (TRU-168): тексты, журнал, согласие, отписка.
    path("messaging/", include("domains.platform.notifications.messaging.urls")),
    path("tasks/", include("domains.platform.tasks.urls")),
    path("leads/", include("domains.platform.leads.urls")),
    path("public/leads/", include("domains.platform.leads.public_urls")),
    path("ai/", include("domains.platform.ai.urls")),
    path("audit/", include("domains.platform.core.audit_urls")),
    path("analytics/", include("domains.platform.analytics.urls")),
    # Ключи публичного API — сторона владельца (TRU-176).
    path("api-keys/", include("domains.platform.public_api.staff_urls")),
    # Кабинет родителя (M4): свой вход по коду и свой токен, не JWT сотрудников.
    path("portal/", include("domains.people.portal.urls")),
    # Объявления для кабинета родителя — сторона сотрудников (TRU-140).
    path("announcements/", include("domains.people.portal.staff_urls")),
    path("parent-requests/", include("domains.people.portal.staff_requests_urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1_patterns)),
    # Публичное API для тарифа Enterprise (TRU-176): свой ключ, свои правила совместимости.
    path("api/public/v1/", include("domains.platform.public_api.urls")),
    # Веб — только frontend2 (React, ADR-004); nginx отдаёт его на всё,
    # что не /api/, /admin/, /static/, /media/ и /healthz/.
    path("", include("domains.platform.core.urls")),
]

if settings.DEBUG:
    # Продакшен отдаёт /media/ через nginx/облачное хранилище напрямую —
    # это только для локальной разработки (WhiteNoise закрывает только
    # STATIC_URL, не MEDIA_URL).
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
