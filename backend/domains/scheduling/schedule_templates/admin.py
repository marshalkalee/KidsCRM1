from django.contrib import admin

from .models import ScheduleTemplate, ScheduleTemplateSlot


class ScheduleTemplateSlotInline(admin.TabularInline):
    model = ScheduleTemplateSlot
    extra = 1
    fields = ["weekday", "start_time", "duration_minutes", "room", "teacher"]


@admin.register(ScheduleTemplate)
class ScheduleTemplateAdmin(admin.ModelAdmin):
    list_display = ["group", "valid_from", "valid_until", "is_active", "generate_weeks_ahead"]
    list_filter = ["group__branch", "group__direction"]
    search_fields = ["group__name"]
    inlines = [ScheduleTemplateSlotInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ScheduleTemplateSlot)
class ScheduleTemplateSlotAdmin(admin.ModelAdmin):
    list_display = ["template", "weekday", "start_time", "duration_minutes", "room", "teacher"]
    list_filter = ["weekday", "room"]
