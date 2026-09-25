"""
Корневой urlconf. Веб — серверный рендеринг Django-шаблонами на «голых»
путях (см. ADR-002). Публичный REST API живёт под /api/v1/ (версионирование
через URL-префикс) — на него же ходят и AJAX-вызовы со страниц (DataTables,
Select2 и т.п.), отдельного «внутреннего» API нет. Каждый домен подключает
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
    path("tasks/", include("domains.platform.tasks.urls")),
    path("leads/", include("domains.platform.leads.urls")),
    path("audit/", include("domains.platform.core.audit_urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(api_v1_patterns)),
    # Веб-страницы (серверный рендеринг). Домен "platform" отдаёт главную —
    # у остальных доменов свои веб-маршруты добавляются по мере надобности,
    # не заводятся заранее пустыми.
    path("", include("domains.platform.core.urls")),
    path("", include("domains.platform.tenants.urls_web")),
    path("", include("domains.people.clients.urls_web")),
    path("", include("domains.money.subscriptions.urls_web")),
    path("", include("domains.scheduling.groups.urls_web")),
    path("payments/", include("domains.money.payments.urls_web")),
]

if settings.DEBUG:
    # Продакшен отдаёт /media/ через nginx/облачное хранилище напрямую —
    # это только для локальной разработки (WhiteNoise закрывает только
    # STATIC_URL, не MEDIA_URL).
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
