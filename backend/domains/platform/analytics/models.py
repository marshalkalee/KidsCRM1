"""
История метрик-снимков (TRU-118, ADR-0006). Долг и заполняемость — это
состояние «на сейчас»; чтобы отчёт показал их динамику (TRU-124), значение
раз в час сохраняется на сегодняшнюю дату центра. Последняя запись дня
перезаписывает прошлую — в истории остаётся состояние на конец дня.
"""

from django.db import models

from domains.platform.core.models import TenantModel


class MetricSnapshot(TenantModel):
    metric = models.CharField(max_length=40)
    # Пусто — вся организация (включая записи без филиала).
    branch = models.ForeignKey(
        "tenants.Branch", on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    date = models.DateField()
    value = models.DecimalField(max_digits=14, decimal_places=1, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "metric", "branch", "date"],
                name="unique_metric_snapshot_per_day",
                nulls_distinct=False,
            ),
        ]
        indexes = [models.Index(fields=["organization", "metric", "date"])]
