import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import domains.platform.notifications.models


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0012_trial_children"),
        ("leads", "0013_alter_lead_phone"),
        ("notifications", "0005_instagram"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TelephonyConnection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("provider", models.CharField(choices=[("console", "Тестовый режим"), ("zadarma", "Zadarma")], default="console", max_length=16)),
                ("status", models.CharField(choices=[("disconnected", "Не подключена"), ("connected", "Подключена"), ("error", "Ошибка")], default="disconnected", max_length=16)),
                ("api_key", models.CharField(blank=True, max_length=255)),
                ("api_secret", models.TextField(blank=True)),
                ("virtual_number", models.CharField(blank=True, max_length=20)),
                ("webhook_secret", models.CharField(blank=True, max_length=100)),
                ("recording_enabled", models.BooleanField(default=False)),
                ("recording_notice_confirmed", models.BooleanField(default=False)),
                ("recording_roles", models.JSONField(default=domains.platform.notifications.models.default_recording_roles)),
                ("recording_retention_days", models.PositiveSmallIntegerField(default=90)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("organization",), name="telephony_connection_unique_org")]},
        ),
        migrations.CreateModel(
            name="CallRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("provider_call_id", models.CharField(max_length=255)),
                ("direction", models.CharField(choices=[("inbound", "Входящий"), ("outbound", "Исходящий")], max_length=16)),
                ("status", models.CharField(choices=[("ringing", "Звонит"), ("answered", "Отвечен"), ("completed", "Завершён"), ("external", "Передан на устройство"), ("missed", "Пропущен"), ("failed", "Ошибка")], default="ringing", max_length=16)),
                ("phone", models.CharField(max_length=20)),
                ("started_at", models.DateTimeField()),
                ("answered_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("duration_seconds", models.PositiveIntegerField(default=0)),
                ("result", models.CharField(blank=True, max_length=255)),
                ("recording_url", models.URLField(blank=True, max_length=1000)),
                ("recording_expires_at", models.DateTimeField(blank=True, null=True)),
                ("seen_at", models.DateTimeField(blank=True, null=True)),
                ("child", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calls", to="clients.child")),
                ("communication_log", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="call_record", to="clients.communicationlog")),
                ("employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calls", to=settings.AUTH_USER_MODEL)),
                ("lead", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calls", to="leads.lead")),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calls", to="clients.parentcontact")),
            ],
            options={
                "ordering": ["-started_at"],
                "indexes": [
                    models.Index(fields=["organization", "status", "-started_at"], name="call_org_status_idx"),
                    models.Index(fields=["organization", "phone", "-started_at"], name="call_org_phone_idx"),
                ],
                "constraints": [models.UniqueConstraint(fields=("organization", "provider_call_id"), name="call_unique_provider_id")],
            },
        ),
    ]
