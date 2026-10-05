from rest_framework.routers import DefaultRouter

from . import views

app_name = "tasks"
router = DefaultRouter()
router.register("", views.TaskViewSet, basename="task")
urlpatterns = router.urls
