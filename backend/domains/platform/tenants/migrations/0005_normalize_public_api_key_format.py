import secrets

from django.db import migrations


def regenerate_keys(apps, schema_editor):
    Organization = apps.get_model("tenants", "Organization")
    for organization in Organization.objects.all():
        organization.public_api_key = secrets.token_urlsafe(32)
        organization.save(update_fields=["public_api_key"])


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0004_organization_public_api_key_and_more"),  # подставь реальное имя предыдущей миграции
    ]
    operations = [
        migrations.RunPython(regenerate_keys, migrations.RunPython.noop),
    ]