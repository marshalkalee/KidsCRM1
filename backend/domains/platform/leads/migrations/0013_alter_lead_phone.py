from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0012_lead_campaigns"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="phone",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
