from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import LessonEnrollmentViewSet, LessonViewSet, StaffAbsenceViewSet

router = DefaultRouter()
router.register("absences", StaffAbsenceViewSet, basename="staff-absence")
router.register("enrollments", LessonEnrollmentViewSet, basename="lesson-enrollment")
router.register("", LessonViewSet, basename="lesson")

# Documented TRU-183 contract. The router action remains available at
# /schedule/substitute/ for the existing frontend convention.
urlpatterns = [
    path(
        "lessons/substitute/",
        LessonViewSet.as_view({"post": "substitute", "delete": "substitute"}),
        name="lesson-substitute",
    ),
    *router.urls,
]
