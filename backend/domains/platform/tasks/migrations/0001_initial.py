import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("leads", "0007_status_change_is_automatic"),
    ]

    operations = [
        migrations.CreateModel(
            name="Task",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("trial_no_show", "Не пришёл на пробное"),
                            ("missing_subscription", "Нет абонемента"),
                            ("other", "Другое"),
                        ],
                        default="other",
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Открыта"),
                            ("done", "Выполнена"),
                            ("cancelled", "Отменена"),
                        ],
                        default="open",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("source_key", models.CharField(blank=True, max_length=100)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="assigned_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "lead",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks",
                        to="leads.lead",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="tenants.organization",
                    ),
                ),
            ],
            options={"ordering": ["status", "due_at", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["organization", "assigned_to", "status", "due_at"],
                name="tasks_task_organiz_6fe9ea_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(
                fields=["organization", "lead", "status"],
                name="tasks_task_organiz_8dbe20_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    models.Q(("source_key", ""), _negated=True),
                    ("deleted_at__isnull", True),
                ),
                fields=("organization", "type", "source_key"),
                name="unique_automatic_task_source",
            ),
        ),
    ]
