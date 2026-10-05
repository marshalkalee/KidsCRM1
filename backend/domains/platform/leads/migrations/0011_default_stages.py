from django.db import migrations

from domains.platform.leads.stages import ensure_default_stages


def forwards(apps, schema_editor):
    Organization = apps.get_model("tenants", "Organization")
    LeadStage = apps.get_model("leads", "LeadStage")
    for organization in Organization.objects.all():
        ensure_default_stages(organization, stage_model=LeadStage)


class Migration(migrations.Migration):
    """Системные этапы TRU-154 у уже существующих организаций — тот же набор
    и те же названия, что были зашиты до кастомизации."""

    dependencies = [("leads", "0010_lead_stages")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
