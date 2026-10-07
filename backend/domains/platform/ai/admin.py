from django.contrib import admin

from .models import AIGeneration, AIUsage


@admin.register(AIUsage)
class AIUsageAdmin(admin.ModelAdmin):
    """Журнал расхода ИИ — только платформа (TRU-160). Сводка по месяцам —
    `manage.py ai_usage_report`."""

    list_display = [
        "created_at",
        "organization",
        "feature",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_usd",
    ]
    list_filter = ["organization", "feature", "model"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AIUsage._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AIGeneration)
class AIGenerationAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "organization",
        "function",
        "prompt_version",
        "model",
        "status",
        "attempts",
        "input_tokens",
        "output_tokens",
    ]
    list_filter = ["organization", "function", "status"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AIGeneration._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
