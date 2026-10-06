from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attendance", "0003_parentnote")]

    operations = [
        migrations.AddField(
            model_name="parentnote",
            name="kind",
            field=models.CharField(
                choices=[("note", "Заметка"), ("homework", "Домашнее задание")],
                default="note",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="parentnote",
            name="valid_until",
            field=models.DateField(blank=True, null=True),
        ),
    ]
