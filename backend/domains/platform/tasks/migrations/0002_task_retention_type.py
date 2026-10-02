from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("tasks", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="type",
            field=models.CharField(
                choices=[
                    ("trial_no_show", "Не пришёл на пробное"),
                    ("missing_subscription", "Нет абонемента"),
                    ("retention", "Удержание клиента"),
                    ("other", "Другое"),
                ],
                default="other",
                max_length=32,
            ),
        )
    ]
