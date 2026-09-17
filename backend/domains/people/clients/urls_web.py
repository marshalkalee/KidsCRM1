"""
Веб-маршруты (серверный рендеринг) — отдельно от urls.py (DRF-роутер под
/api/v1/, см. config/urls.py). Тот же принцип, что у tenants/urls_web.py.
"""

from django.urls import path

from . import web_views

app_name = "clients_web"

urlpatterns = [
    path(
        "clients/children/<uuid:child_id>/contacts/",
        web_views.child_contacts_list,
        name="child-contacts",
    ),
    path(
        "clients/children/<uuid:child_id>/contacts/create/",
        web_views.child_contact_create,
        name="child-contact-create",
    ),
    path(
        "clients/children/<uuid:child_id>/contacts/<uuid:pk>/edit/",
        web_views.child_contact_edit,
        name="child-contact-edit",
    ),
    path(
        "clients/children/<uuid:child_id>/contacts/<uuid:pk>/detach/",
        web_views.child_contact_detach,
        name="child-contact-detach",
    ),
]
