from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ("clients", "0012_trial_children"),
        ("notifications", "0002_messagetemplate_messagingconsent_outboundmessage"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagetemplate",
            name="provider_template_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="provider_status",
            field=models.CharField(
                choices=[
                    ("draft", "Черновик"),
                    ("pending", "На проверке"),
                    ("approved", "Одобрен"),
                    ("rejected", "Отклонён"),
                ],
                default="draft",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="rejection_reason",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="outboundmessage",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "В очереди"),
                    ("deferred", "Ждёт утра (тихие часы)"),
                    ("sending", "Отправляется"),
                    ("sent", "Отправлено"),
                    ("delivered", "Доставлено"),
                    ("read", "Прочитано"),
                    ("failed", "Не дошло"),
                    ("no_consent", "Нет согласия"),
                    ("opted_out", "Родитель отписался"),
                    ("no_channel", "Нет канала (нет email, WhatsApp не подключён)"),
                ],
                default="queued",
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="WhatsAppConnection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("mode", models.CharField(choices=[("console", "Тестовый режим"), ("meta", "Meta Cloud API")], default="console", max_length=16)),
                ("status", models.CharField(choices=[("disconnected", "Не подключён"), ("connected", "Подключён"), ("error", "Ошибка")], default="disconnected", max_length=16)),
                ("waba_id", models.CharField(blank=True, max_length=100)),
                ("phone_number_id", models.CharField(blank=True, max_length=100)),
                ("business_phone", models.CharField(blank=True, max_length=20)),
                ("access_token", models.TextField(blank=True)),
                ("webhook_verify_token", models.CharField(blank=True, max_length=100)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
            ],
            options={"abstract": False},
        ),
        migrations.AddConstraint(
            model_name="whatsappconnection",
            constraint=models.UniqueConstraint(fields=("organization",), name="whatsapp_connection_unique_org"),
        ),
        migrations.CreateModel(
            name="WhatsAppContactWindow",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("last_inbound_at", models.DateTimeField()),
                ("organization", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="tenants.organization")),
                ("parent", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="whatsapp_windows", to="clients.parentcontact")),
            ],
            options={"abstract": False},
        ),
        migrations.AddConstraint(
            model_name="whatsappcontactwindow",
            constraint=models.UniqueConstraint(fields=("organization", "parent"), name="whatsapp_window_unique_parent"),
        ),
    ]
