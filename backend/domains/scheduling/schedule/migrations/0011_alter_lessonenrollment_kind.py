from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("schedule", "0010_trial_booking_changes")]

    operations = [
        migrations.AlterField(
            model_name="lessonenrollment",
            name="kind",
            field=models.CharField(
                choices=[
                    ("regular", "Обычная запись"),
                    ("makeup", "Отработка"),
                    ("trial", "Пробное"),
                ],
                max_length=16,
            ),
        ),
    ]
