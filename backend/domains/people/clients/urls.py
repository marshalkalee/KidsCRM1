from rest_framework.routers import DefaultRouter

from . import views

app_name = "clients"

router = DefaultRouter()
router.register("children", views.ChildViewSet, basename="child")
router.register("parents", views.ParentContactViewSet, basename="parent-contact")
router.register("child-contacts", views.ChildContactViewSet, basename="child-contact")

urlpatterns = router.urls
