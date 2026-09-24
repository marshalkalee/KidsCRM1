"""
Веб-маршруты (серверный рендеринг) — отдельно от urls.py (DRF-роутер под
/api/v1/, см. config/urls.py). Тот же принцип, что у tenants/urls_web.py.
"""

from django.urls import path

from . import import_views, web_views

app_name = "clients_web"

urlpatterns = [
    path("clients/search/", web_views.global_search, name="global-search"),
    path("clients/import/", import_views.child_import_upload, name="child-import-upload"),
    path(
        "clients/import/mapping/",
        import_views.child_import_mapping_confirm,
        name="child-import-mapping-confirm",
    ),
    path(
        "clients/import/jobs/<uuid:job_id>/",
        import_views.child_import_job_status,
        name="child-import-job-status",
    ),
    path(
        "clients/import/jobs/<uuid:job_id>/report.xlsx",
        import_views.child_import_report_download,
        name="child-import-report-download",
    ),
    path(
        "clients/import/jobs/<uuid:job_id>/decisions/",
        import_views.child_import_decisions,
        name="child-import-decisions",
    ),
    path(
        "clients/import/jobs/<uuid:job_id>/execute/",
        import_views.child_import_execute,
        name="child-import-execute",
    ),
    path(
        "clients/import/jobs/<uuid:job_id>/rollback/",
        import_views.child_import_rollback,
        name="child-import-rollback",
    ),
    path("clients/children/", web_views.child_list, name="child-list"),
    path("clients/children/data/", web_views.child_list_data, name="child-list-data"),
    path("clients/children/create/", web_views.child_create, name="child-create"),
    path(
        "clients/children/photo-upload/",
        web_views.child_photo_upload,
        name="child-photo-upload",
    ),
    path("clients/children/<uuid:child_id>/", web_views.child_card, name="child-card"),
    path("clients/children/<uuid:child_id>/edit/", web_views.child_edit, name="child-edit"),
    path(
        "clients/children/<uuid:child_id>/tabs/contacts/",
        web_views.child_tab_contacts,
        name="child-tab-contacts",
    ),
    path(
        "clients/children/<uuid:child_id>/tabs/communications/",
        web_views.child_tab_communications,
        name="child-tab-communications",
    ),
    path(
        "clients/children/<uuid:child_id>/communications/create/",
        web_views.child_communication_create,
        name="child-communication-create",
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
    path("clients/parents/", web_views.parent_list, name="parent-list"),
    path("clients/parents/create/", web_views.parent_create, name="parent-create"),
    path("clients/parents/<uuid:pk>/", web_views.parent_card, name="parent-card"),
    path("clients/parents/<uuid:pk>/edit/", web_views.parent_edit, name="parent-edit"),
    path("clients/parents/<uuid:pk>/delete/", web_views.parent_delete, name="parent-delete"),
    path(
        "clients/parents/<uuid:pk>/communications/create/",
        web_views.parent_communication_create,
        name="parent-communication-create",
    ),
]
