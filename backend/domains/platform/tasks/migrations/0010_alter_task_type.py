from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0009_task_comment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="type",
            field=models.CharField(
                choices=[
                    ("trial_no_show", "Не пришёл на пробное"),
                    ("missing_subscription", "Нет абонемента"),
                    ("retention", "Удержание клиента"),
                    ("parent_request", "Запрос родителя"),
                    ("contact", "Связаться"),
                    ("call_back", "Перезвонить"),
                    ("payment_reminder", "Напомнить об оплате"),
                    ("trial_signup", "Записать на пробное"),
                    ("renewal_offer", "Предложить продление"),
                    ("other", "Другое"),
                ],
                default="other",
                max_length=32,
            ),
        ),
    ]
