from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("signup/", views.signup_view, name="signup"),
    path("logout/", views.logout_view, name="logout"),
    path("switch-branch/", views.switch_branch, name="switch-branch"),
    path("switch-language/", views.switch_language, name="switch-language"),
    path("dev/components/", views.components_demo, name="components-demo"),
    path("healthz/", views.healthz, name="healthz"),
]
