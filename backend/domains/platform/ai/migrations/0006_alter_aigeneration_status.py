from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0005_aigeneration_parameters_aicontentdraft")]

    operations = [
        migrations.AlterField(
            model_name="aigeneration",
            name="status",
            field=models.CharField(
                choices=[
                    ("queued", "В очереди"),
                    ("running", "Выполняется"),
                    ("succeeded", "Готово"),
                    ("provider_unavailable", "Провайдер недоступен"),
                    ("schema_error", "Ответ не прошёл проверку"),
                    ("limit_exhausted", "Лимит исчерпан"),
                    ("no_key", "ИИ не настроен"),
                    ("input_too_large", "Слишком большой запрос"),
                    ("cancelled", "Отменено пользователем"),
                ],
                default="queued",
                max_length=32,
            ),
        ),
    ]
