"""
Прогресс фонового импорта (тикет «запись данных с разрешением дублей»:
импорт 5000 строк идёт заметное время, экран не должен выглядеть
зависшим).

Не поле ImportJob: запись идёт одной транзакцией (import_service.
execute_import), и обновления ImportJob изнутри неё не видны странице
статуса до самого конца. Поэтому — отдельный кэш в Redis (CACHES
"import_progress"), общий для воркера и веба. Прогресс — только
подсказка для экрана: недоступный Redis не должен ронять импорт, поэтому
любые ошибки кэша здесь глушатся.
"""

import logging

from django.core.cache import caches

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 24 * 60 * 60


class Phase:
    CHECKING = "checking"  # поиск дублей (resolve_rows)
    WRITING = "writing"  # запись (execute_import)


def _key(job_id) -> str:
    return f"job:{job_id}"


def set_progress(job_id, *, phase: str, done: int, total: int) -> None:
    try:
        caches["import_progress"].set(
            _key(job_id), {"phase": phase, "done": done, "total": total}, _TIMEOUT_SECONDS
        )
    except Exception:  # noqa: BLE001 — прогресс не стоит упавшего импорта
        logger.warning("Не удалось записать прогресс импорта %s", job_id, exc_info=True)


def get_progress(job_id) -> dict | None:
    try:
        return caches["import_progress"].get(_key(job_id))
    except Exception:  # noqa: BLE001
        logger.warning("Не удалось прочитать прогресс импорта %s", job_id, exc_info=True)
        return None


def reporter(job_id, phase: str):
    """Колбэк on_progress(done, total) для resolve_rows/execute_import."""

    def report(done: int, total: int) -> None:
        set_progress(job_id, phase=phase, done=done, total=total)

    return report
