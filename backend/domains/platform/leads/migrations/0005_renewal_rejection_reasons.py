from django.db import migrations

# Копия списка из leads/defaults.py на момент миграции.
REASONS = ["Дорого", "Ушли из центра", "Сменили направление", "Переезд", "Другое"]


def add_renewal_reasons(apps, schema_editor):
    """Причины отказа от продления (TRU-98) у организаций, созданных раньше."""
    Organization = apps.get_model("tenants", "Organization")
    Reason = apps.get_model("leads", "LeadRejectionReason")
    for organization in Organization.objects.all():
        if Reason.objects.filter(organization=organization, kind="renewal").exists():
            continue
        Reason.objects.bulk_create(
            Reason(organization=organization, name=name, kind="renewal") for name in REASONS
        )


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0004_renewal_leads"),
    ]

    operations = [migrations.RunPython(add_renewal_reasons, migrations.RunPython.noop)]
