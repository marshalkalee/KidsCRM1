import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0002_attendance_is_retroactive_edit"),
        ("clients", "0012_trial_children"),
        ("schedule", "0010_trial_booking_changes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ParentNote",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("scope", models.CharField(choices=[("group", "По группе"), ("child", "По ребёнку")], max_length=16)),
                ("body", models.TextField(max_length=1000)),
                ("author", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="parent_notes", to=settings.AUTH_USER_MODEL)),
                ("child", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="parent_notes", to="clients.child")),
                ("lesson", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="parent_notes", to="schedule.lesson")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="parentnote",
            constraint=models.CheckConstraint(
                condition=models.Q(models.Q(("child__isnull", True), ("scope", "group")), models.Q(("child__isnull", False), ("scope", "child")), _connector="OR"),
                name="parent_note_scope_matches_child",
            ),
        ),
        migrations.AddIndex(
            model_name="parentnote",
            index=models.Index(fields=["organization", "lesson", "created_at"], name="attendance__organiz_355c6a_idx"),
        ),
    ]
