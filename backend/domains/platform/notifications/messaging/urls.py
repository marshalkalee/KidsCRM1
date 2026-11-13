from django.urls import include, path

from . import views

app_name = "messaging"

urlpatterns = [
    path("telephony/", views.telephony_connection, name="telephony-connection"),
    path("telephony/calls/", views.telephony_calls, name="telephony-calls"),
    path("telephony/outgoing/", views.telephony_outgoing, name="telephony-outgoing"),
    path(
        "telephony/webhook/<str:secret>/",
        views.telephony_webhook,
        name="telephony-webhook",
    ),
    path(
        "telephony/calls/<uuid:call_id>/seen/",
        views.telephony_seen,
        name="telephony-seen",
    ),
    path(
        "telephony/calls/<uuid:call_id>/promote/",
        views.telephony_promote,
        name="telephony-promote",
    ),
    path(
        "telephony/calls/<uuid:call_id>/recording/",
        views.telephony_recording,
        name="telephony-recording",
    ),
    path("settings/", views.messaging_settings, name="settings"),
    path("whatsapp/", views.whatsapp_connection, name="whatsapp-connection"),
    path("whatsapp/test/", views.whatsapp_test, name="whatsapp-test"),
    path("whatsapp/templates/sync/", views.whatsapp_sync_templates, name="whatsapp-sync"),
    path("whatsapp/webhook/", views.whatsapp_webhook, name="whatsapp-webhook"),
    path("whatsapp/numbers/", views.whatsapp_numbers, name="whatsapp-numbers"),
    path(
        "whatsapp/numbers/<uuid:connection_id>/",
        views.whatsapp_number,
        name="whatsapp-number",
    ),
    path(
        "whatsapp/evolution/<str:secret>/",
        views.evolution_webhook,
        name="whatsapp-evolution-webhook",
    ),
    path("whatsapp/inbox/", views.whatsapp_inbox, name="whatsapp-inbox"),
    path(
        "whatsapp/inbox/<uuid:message_id>/resolve/",
        views.whatsapp_inbox_resolve,
        name="whatsapp-inbox-resolve",
    ),
    path("whatsapp/bulk/", views.whatsapp_bulk, name="whatsapp-bulk"),
    path("whatsapp/reply/", views.whatsapp_reply, name="whatsapp-reply"),
    path("whatsapp/status/", views.whatsapp_status, name="whatsapp-status"),
    path("whatsapp/send/", views.whatsapp_send, name="whatsapp-send"),
    path("whatsapp/thread/", views.whatsapp_thread, name="whatsapp-thread"),
    path(
        "whatsapp/messages/<str:direction>/<uuid:message_id>/delete/",
        views.whatsapp_delete_message,
        name="whatsapp-delete-message",
    ),
    path(
        "whatsapp/media/<str:direction>/<uuid:message_id>/",
        views.whatsapp_media,
        name="whatsapp-media",
    ),
    path("instagram/", views.instagram_connection, name="instagram-connection"),
    path("instagram/test/", views.instagram_test, name="instagram-test"),
    path("instagram/webhook/", views.instagram_webhook, name="instagram-webhook"),
    path("instagram/inbox/", views.instagram_inbox, name="instagram-inbox"),
    path(
        "instagram/inbox/<uuid:message_id>/resolve/",
        views.instagram_inbox_resolve,
        name="instagram-inbox-resolve",
    ),
    path(
        "instagram/inbox/<uuid:message_id>/promote/",
        views.instagram_promote,
        name="instagram-promote",
    ),
    path(
        "instagram/inbox/<uuid:message_id>/reply/",
        views.instagram_reply,
        name="instagram-reply",
    ),
    path("templates/", views.templates, name="templates"),
    path("templates/<str:event>/<str:language>/", views.template_detail, name="template-detail"),
    path("messages/", views.journal, name="journal"),
    path("parents/<uuid:parent_id>/consent/", views.parent_consent, name="parent-consent"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    # Вебхуки почтового провайдера: anymail/<esp>/tracking/.
    path("anymail/", include("anymail.urls")),
]
