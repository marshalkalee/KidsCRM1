from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0007_merge_content_studio_digest")]

    operations = [
        migrations.AddField(
            model_name="aidigest",
            name="language",
            field=models.CharField(
                choices=[("ru", "Русский"), ("kk", "Қазақша"), ("en", "English")],
                default="ru",
                max_length=2,
            ),
        ),
    ]
