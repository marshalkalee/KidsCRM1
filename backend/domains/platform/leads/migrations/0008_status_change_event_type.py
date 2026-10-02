from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leads", "0007_status_change_is_automatic")]

    operations = [
        migrations.AddField(
            model_name="leadstatuschange",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("status_change", "Смена статуса"),
                    ("trial_rescheduled", "Пробное перенесено"),
                ],
                default="status_change",
                max_length=24,
            ),
        )
    ]
