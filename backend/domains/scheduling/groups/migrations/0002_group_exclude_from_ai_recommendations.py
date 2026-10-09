from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("groups", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="group",
            name="exclude_from_ai_recommendations",
            field=models.BooleanField(
                default=False,
                help_text="Для индивидуальных, конкурсных и других намеренно малых групп.",
                verbose_name="Не предлагать продвижение",
            ),
        )
    ]
