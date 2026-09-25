from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

app_name = "users"

router = DefaultRouter()
router.register("", views.UserViewSet, basename="user")

urlpatterns = router.urls + [
    path("auth/register/", views.RegisterView.as_view(), name="register"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="logout"),
    path("auth/logout-all/", views.LogoutAllView.as_view(), name="logout-all"),
    path("auth/invite/", views.InviteStaffView.as_view(), name="invite"),
    path("auth/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    path("auth/me/", views.MeView.as_view(), name="me"),
]
