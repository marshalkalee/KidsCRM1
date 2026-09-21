from rest_framework_nested import routers

from .views import ScheduleTemplateSlotViewSet, ScheduleTemplateViewSet

router = routers.SimpleRouter()
router.register("", ScheduleTemplateViewSet, basename="schedule-template")

slots_router = routers.NestedSimpleRouter(router, "", lookup="template")
slots_router.register("slots", ScheduleTemplateSlotViewSet, basename="schedule-template-slot")

urlpatterns = router.urls + slots_router.urls
