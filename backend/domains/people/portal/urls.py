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
        "children/<uuid:child_id>/summary/", views.ChildSummaryView.as_view(), name="child-summary"
    ),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/phone/", views.PhoneChangeView.as_view(), name="phone-change"),
]
