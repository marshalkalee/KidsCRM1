# Generated for TRU-100.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("clients", "0011_importjob_decisions_and_rollback"),
    ]

    operations = [
        migrations.AddField(
            model_name="child",
            name="birth_date_is_estimated",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="child",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[("male", "Мужской"), ("female", "Женский")],
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="child",
            name="status",
            field=models.CharField(
                choices=[
                    ("trial", "Пробный"),
                    ("active", "Активен"),
                    ("paused", "Приостановлен"),
                    ("left", "Ушёл"),
                ],
                default="active",
                max_length=10,
            ),
        ),
    ]
