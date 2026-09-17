from rest_framework.routers import DefaultRouter

from . import views

app_name = "clients"

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")

urlpatterns = router.urls
