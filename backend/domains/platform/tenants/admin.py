from django.contrib import admin

from .models import Branch, Organization, Room


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "subscription_status", "plan", "is_active", "created_at"]
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
