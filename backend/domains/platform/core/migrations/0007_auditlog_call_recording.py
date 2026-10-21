from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0006_auditlog_import_actions")]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="action",
            field=models.CharField(
                choices=[
                    ("create", "Создание"), ("update", "Изменение"),
                    ("delete", "Удаление"), ("freeze", "Заморозка"),
                    ("unfreeze", "Разморозка"), ("extend", "Продление"),
                    ("adjust", "Корректировка"), ("grant", "Выдача прав"),
                    ("revoke", "Отзыв прав"), ("cancel", "Отмена"),
                    ("reschedule", "Перенос"),
                    ("mark_attendance", "Отметка посещаемости"),
                    ("enroll", "Запись на занятие поверх группы"),
                    ("unenroll", "Отмена записи поверх группы"),
                    ("import", "Импорт"), ("import_rollback", "Откат импорта"),
                    ("parent_login", "Вход родителя в кабинет"),
                    ("play_call_recording", "Прослушивание записи звонка"),
                ],
                max_length=50,
            ),
        )
    ]
