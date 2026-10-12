from rest_framework.routers import DefaultRouter

from .views import LessonEnrollmentViewSet, LessonViewSet, StaffAbsenceViewSet

router = DefaultRouter()
router.register("absences", StaffAbsenceViewSet, basename="staff-absence")
router.register("enrollments", LessonEnrollmentViewSet, basename="lesson-enrollment")
router.register("", LessonViewSet, basename="lesson")

urlpatterns = router.urls
