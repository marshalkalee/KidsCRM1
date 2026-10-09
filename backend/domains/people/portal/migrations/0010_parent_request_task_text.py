"""Задачи по запросам родителей — человеческий заголовок и описание
(вместо «Запрос родителя: отмена» и строки занятия со служебным id)."""

from django.db import migrations


def rewrite(apps, schema_editor):
    from domains.people.portal.lesson_requests import task_text
    from domains.people.portal.models import ParentLessonRequest
    from domains.platform.tasks.models import Task

    tasks = Task.objects.filter(type="parent_request", source_key__startswith="parent-request:")
    for task in tasks:
        request_id = task.source_key.split(":", 1)[1]
        parent_request = (
            ParentLessonRequest.objects.select_related(
                "organization", "lesson__group__branch", "lesson__room__branch"
            )
            .filter(pk=request_id)
            .first()
        )
        if parent_request is None:
            continue
        task.title, task.description = task_text(parent_request)
        task.save(update_fields=["title", "description", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0009_parentaccount_notification_prefs_pushsubscription"),
        ("tasks", "0008_merge_parent_cancel_task_types"),
    ]

    operations = [migrations.RunPython(rewrite, migrations.RunPython.noop)]
