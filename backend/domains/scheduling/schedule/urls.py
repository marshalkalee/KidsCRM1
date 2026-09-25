from rest_framework.routers import DefaultRouter

from .views import LessonEnrollmentViewSet, LessonViewSet

router = DefaultRouter()
router.register("enrollments", LessonEnrollmentViewSet, basename="lesson-enrollment")
router.register("", LessonViewSet, basename="lesson")

urlpatterns = router.urls
