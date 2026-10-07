from django.urls import include, path

from . import views

app_name = "messaging"

urlpatterns = [
    path("settings/", views.messaging_settings, name="settings"),
    path("templates/", views.templates, name="templates"),
    path("templates/<str:event>/<str:language>/", views.template_detail, name="template-detail"),
    path("messages/", views.journal, name="journal"),
    path("parents/<uuid:parent_id>/consent/", views.parent_consent, name="parent-consent"),
    path("unsubscribe/<str:token>/", views.unsubscribe, name="unsubscribe"),
    # Вебхуки почтового провайдера: anymail/<esp>/tracking/.
    path("anymail/", include("anymail.urls")),
]
