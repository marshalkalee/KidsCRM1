# Celery ищет задачи в tasks.py приложения — задача рассылок живёт в messaging/.
from .messaging.tasks import deliver_message  # noqa: F401
