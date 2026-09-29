from django.contrib import admin

from .models import BalanceDiscrepancy


@admin.register(BalanceDiscrepancy)
class BalanceDiscrepancyAdmin(admin.ModelAdmin):
    """Отчёт сверки остатка (TRU-61): если расхождения появляются регулярно — это баг."""

    list_display = ["found_at", "organization", "subscription", "cached_value", "recomputed_value"]
    list_filter = ["organization", "found_at"]
    search_fields = ["subscription__child__full_name"]
    list_select_related = [
        "organization",
        "subscription__child",
        "subscription__subscription_type_version",
    ]
    readonly_fields = list_display

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
