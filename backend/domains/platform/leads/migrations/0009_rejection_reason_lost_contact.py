from django.db import migrations, models

# Копия из leads/defaults.py на момент миграции: у уже существующих центров
# причина «Не пришёл на пробное» — потеря контакта, а не возражение (TRU-117).
LOST_CONTACT_REASONS = ["Не пришёл на пробное"]


def mark_lost_contact(apps, schema_editor):
    Reason = apps.get_model("leads", "LeadRejectionReason")
    Reason.objects.filter(kind="new", name__in=LOST_CONTACT_REASONS).update(is_lost_contact=True)


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0008_status_change_event_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="leadrejectionreason",
            name="is_lost_contact",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_lost_contact, migrations.RunPython.noop),
    ]
