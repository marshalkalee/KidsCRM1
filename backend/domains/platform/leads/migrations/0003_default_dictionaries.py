from django.db import migrations

# Копия списков из leads/defaults.py на момент миграции: миграция не должна
# меняться, если значения по умолчанию для новых организаций поменяют.
SOURCES = ["Instagram", "WhatsApp", "Сайт", "Звонок", "Рекомендация", "Офлайн", "Другое"]
REJECTION_REASONS = ["Дорого", "Неудобное время", "Далеко", "Не подошло направление", "Не пришёл на пробное", "Другое"]


def add_defaults(apps, schema_editor):
    """Справочники по умолчанию у организаций, созданных до TRU-93."""
    Organization = apps.get_model("tenants", "Organization")
    for model_name, names in (("LeadSource", SOURCES), ("LeadRejectionReason", REJECTION_REASONS)):
        model = apps.get_model("leads", model_name)
        for organization in Organization.objects.all():
            if model.objects.filter(organization=organization).exists():
                continue
            model.objects.bulk_create(model(organization=organization, name=name) for name in names)


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0002_status_change_reason_related_name"),
        ("tenants", "0001_initial"),
    ]

    operations = [migrations.RunPython(add_defaults, migrations.RunPython.noop)]
