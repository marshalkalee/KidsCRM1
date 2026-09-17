from django.contrib import admin

from .models import Group, GroupMembership


class GroupMembershipInline(admin.TabularInline):
    model = GroupMembership
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["child", "joined_at", "left_at", "note", "created_at"]


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ["name", "branch", "direction", "capacity", "status", "created_at"]
    list_filter = ["status", "branch", "direction"]
    search_fields = ["name"]
    filter_horizontal = ["teachers"]
    inlines = [GroupMembershipInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GroupMembership)
class GroupMembershipAdmin(admin.ModelAdmin):
    list_display = ["child", "group", "joined_at", "left_at", "is_active"]
    list_filter = ["group", "left_at"]
    search_fields = ["child__first_name", "child__last_name"]
    readonly_fields = ["created_at"]
