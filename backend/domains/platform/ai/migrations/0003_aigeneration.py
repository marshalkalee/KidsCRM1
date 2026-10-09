import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai", "0002_conversation_pseudonyms"),
        ("tenants", "0003_direction"),
    ]

    operations = [
        migrations.CreateModel(
            name="AIGeneration",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("function", models.CharField(max_length=64)),
                ("prompt_version", models.CharField(max_length=32)),
                ("provider", models.CharField(blank=True, max_length=20)),
                ("model", models.CharField(blank=True, max_length=100)),
                ("status", models.CharField(choices=[("queued", "В очереди"), ("running", "Выполняется"), ("succeeded", "Готово"), ("provider_unavailable", "Провайдер недоступен"), ("schema_error", "Ответ не прошёл проверку"), ("limit_exhausted", "Лимит исчерпан"), ("no_key", "ИИ не настроен"), ("input_too_large", "Слишком большой запрос")], default="queued", max_length=32)),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("request_chars", models.PositiveIntegerField(default=0)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("error_detail", models.CharField(blank=True, max_length=500)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="aigeneration", index=models.Index(fields=["organization", "function", "-created_at"], name="ai_aigenera_organiz_284c82_idx")),
        migrations.AddIndex(model_name="aigeneration", index=models.Index(fields=["organization", "status", "-created_at"], name="ai_aigenera_organiz_8771a2_idx")),
    ]
