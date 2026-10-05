from rest_framework.routers import DefaultRouter

from .views import (
    LeadCampaignViewSet,
    LeadRejectionReasonViewSet,
    LeadSourceViewSet,
    LeadStageViewSet,
    LeadViewSet,
)

app_name = "leads"

router = DefaultRouter()
# Справочники — до заявок: иначе "sources" ловится как id заявки.
router.register("sources", LeadSourceViewSet, basename="lead-source")
router.register("campaigns", LeadCampaignViewSet, basename="lead-campaign")
router.register("stages", LeadStageViewSet, basename="lead-stage")
router.register("rejection-reasons", LeadRejectionReasonViewSet, basename="lead-rejection-reason")
router.register("", LeadViewSet, basename="lead")

urlpatterns = router.urls
