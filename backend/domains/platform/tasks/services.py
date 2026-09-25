"""
M1-заглушка (TRU-50, согласовано с Bekzat): «ребёнок без абонемента —
флаг + автозадача администратору» (ТЗ п. 4.3). Саму модель Task, её API и
экран делает Bekzat в M2 — domains.platform.tasks сейчас пустой каркас
(models.py/views.py/serializers.py — по одной строке импорта). Чтобы стык
между доменами не потерялся при передаче, вызов уже происходит из
Attendance._notify_missing_subscription() в правильный момент — здесь
пока no-op, безопасно заменяемый на реальное создание Task без изменений
на стороне вызывающего кода.
"""


def create_admin_task_for_missing_subscription(*, attendance):
    """attendance — domains.scheduling.attendance.models.Attendance с уже
    выставленным no_subscription_flag=True. Ничего не делает в M1."""
    return None
