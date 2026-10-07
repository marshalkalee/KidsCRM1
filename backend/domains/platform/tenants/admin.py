from django.contrib import admin

from .models import Branch, Organization, Room


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "slug",
        "subscription_status",
        "plan",
        "ai_enabled",
        "ai_monthly_limit_kzt",
        "is_active",
        "created_at",
    ]
    list_filter = ["ai_enabled", "subscription_status"]
    # Опцию ИИ и её лимит включает платформа (TRU-160) — правка прямо в списке.
    list_editable = ["ai_enabled", "ai_monthly_limit_kzt"]
    search_fields = ["name", "slug"]


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ["name", "organization", "phone", "created_at"]
    list_filter = ["organization"]
    search_fields = ["name"]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ["name", "branch", "capacity", "created_at"]
    list_filter = ["branch__organization", "branch"]
    search_fields = ["name"]
