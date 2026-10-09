from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("auth/request-code/", views.RequestCodeView.as_view(), name="request-code"),
    path("auth/verify/", views.VerifyCodeView.as_view(), name="verify"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/sessions/", views.SessionsView.as_view(), name="sessions"),
    path(
        "auth/sessions/<uuid:session_id>/", views.SessionDetailView.as_view(), name="session-detail"
    ),
    path("me/", views.MeView.as_view(), name="me"),
    path("children/<uuid:child_id>/", views.ChildDetailView.as_view(), name="child"),
    path(
        "children/<uuid:child_id>/attendance/",
        views.ChildAttendanceView.as_view(),
        name="child-attendance",
    ),
    path(
        "children/<uuid:child_id>/schedule/",
        views.ChildScheduleView.as_view(),
        name="child-schedule",
    ),
    path(
        "children/<uuid:child_id>/makeups/<uuid:attendance_id>/",
        views.ChildMakeupView.as_view(),
        name="child-makeup",
    ),
    path(
        "children/<uuid:child_id>/lesson-request-options/",
        views.ChildLessonRequestOptionsView.as_view(),
        name="child-lesson-request-options",
    ),
    path(
        "children/<uuid:child_id>/lesson-requests/",
        views.ChildLessonRequestsView.as_view(),
        name="child-lesson-requests",
    ),
    path(
        "children/<uuid:child_id>/summary/",
        views.ChildSummaryView.as_view(),
        name="child-summary",
    ),
    path("children/<uuid:child_id>/money/", views.ChildMoneyView.as_view(), name="child-money"),
    path(
        "children/<uuid:child_id>/notes/",
        views.ChildParentNotesView.as_view(),
        name="child-parent-notes",
    ),
    path(
        "children/<uuid:child_id>/notes/<uuid:note_id>/read/",
        views.ChildParentNoteReadView.as_view(),
        name="child-parent-note-read",
    ),
    path("announcements/", views.AnnouncementsView.as_view(), name="announcements"),
    path(
        "announcements/<uuid:announcement_id>/read/",
        views.AnnouncementReadView.as_view(),
        name="announcement-read",
    ),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/phone/", views.PhoneChangeView.as_view(), name="phone-change"),
    path("notifications/", views.NotificationsView.as_view(), name="notifications"),
    path("push/", views.PushSubscriptionView.as_view(), name="push"),
]
