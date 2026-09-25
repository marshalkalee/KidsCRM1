"""Точка вызова автозадачи «напомнить об оплате» (ТЗ п. 4.4, 4.5).
Сама задача — M2 (домен platform.tasks ещё пуст). На M1 — заглушка,
по тому же принципу, что statuses.suggest_renewal (TRU-62)."""


def create_debt_reminder_task(child, subscription) -> None:
    pass
