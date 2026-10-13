import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("schedule", "0013_staff_absence"),
    ]

    operations = [
        migrations.AddField(
            model_name="lesson",
            name="original_teacher",
            field=models.ForeignKey(
                blank=True,
                help_text="Заполняется только на время замены преподавателя.",
                limit_choices_to={"role": "teacher"},
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="originally_taught_lessons",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Преподаватель по расписанию",
            ),
        ),
    ]
