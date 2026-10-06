from django.contrib import admin

from .models import ParentNote


@admin.register(ParentNote)
class ParentNoteAdmin(admin.ModelAdmin):
    list_display = ["lesson", "scope", "child", "author", "created_at"]
    list_filter = ["scope", "organization"]
    search_fields = ["body", "child__full_name", "author__full_name"]
