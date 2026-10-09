from django.urls import include, path

from . import views

app_name = "messaging"

urlpatterns = [
    path("settings/", views.messaging_settings, name="settings"),
    path("whatsapp/", views.whatsapp_connection, name="whatsapp-connection"),
    path("whatsapp/test/", views.whatsapp_test, name="whatsapp-test"),
    path("whatsapp/templates/sync/", views.whatsapp_sync_templates, name="whatsapp-sync"),
    path("whatsapp/webhook/", views.whatsapp_webhook, name="whatsapp-webhook"),
    path("whatsapp/bulk/", views.whatsapp_bulk, name="whatsapp-bulk"),
    path("whatsapp/reply/", views.whatsapp_reply, name="whatsapp-reply"),
    path("templates/", views.templates, name="templates"),
    path("templates/<str:event>/<str:language>/", views.template_detail, name="template-detail"),
    path("messages/", views.journal, name="journal"),
    path("parents/<uuid:parent_id>/consent/", views.parent_consent, name="parent-consent"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    # Вебхуки почтового провайдера: anymail/<esp>/tracking/.
    path("anymail/", include("anymail.urls")),
]
