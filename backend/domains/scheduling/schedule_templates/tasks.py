"""
Celery задачи для генерации занятий из шаблонов расписания.

Идемпотентность гарантируется в services.generate_lessons_from_template —
повторный запуск не создаёт дублей (проверяет exists() перед созданием).
"""

import logging

from celery import shared_task
from django.utils import timezone

from domains.scheduling.schedule_templates.models import ScheduleTemplate
from domains.scheduling.schedule_templates.services import generate_lessons_from_template

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_lessons_for_template(self, template_id: str):
    try:
        template = (
            ScheduleTemplate.objects.select_related("group", "group__organization")
            .prefetch_related("slots")
            .get(pk=template_id)
        )
    except ScheduleTemplate.DoesNotExist:
        logger.warning("ScheduleTemplate %s не найден — пропускаем", template_id)
        return

    if not template.is_active:
        logger.info(
            "Шаблон %s неактивен (группа: %s) — пропускаем",
            template_id,
            template.group,
        )
        return

    try:
        result = generate_lessons_from_template(template)
        logger.info(
            "Шаблон %s (группа: %s): создано %d, пропущено %d",
            template_id,
            template.group,
            len(result["created"]),
            result["skipped"],
        )
        return {
            "template_id": str(template_id),
            "group": str(template.group),
            "created": len(result["created"]),
            "skipped": result["skipped"],
        }
    except Exception as exc:
        logger.error(
            "Ошибка генерации для шаблона %s: %s",
            template_id,
            exc,
            exc_info=True,
        )
        raise self.retry(exc=exc) from exc


@shared_task
def generate_lessons_for_all_active_templates():
    today = timezone.localdate()

    active_templates = (
        ScheduleTemplate.objects.filter(
            deleted_at__isnull=True,
            valid_from__lte=today,
        )
        .filter(models_q_valid_until_null_or_future(today))
        .values_list("id", flat=True)
    )

    count = 0
    for template_id in active_templates:
        generate_lessons_for_template.delay(str(template_id))
        count += 1

    logger.info("Запущена генерация для %d активных шаблонов", count)
    return {"scheduled": count}


def models_q_valid_until_null_or_future(today):
    from django.db.models import Q

    return Q(valid_until__isnull=True) | Q(valid_until__gte=today)
