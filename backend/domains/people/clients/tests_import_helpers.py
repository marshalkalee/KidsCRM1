"""Общие помощники тестов импорта детей (были в тестах серверных экранов
импорта, удалённых в TRU-88): Excel-файл из строк и синхронный запуск
Celery-задач без брокера."""

import io
from unittest import mock

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile

from .tasks import run_dry_run_job, run_import_job

HEADERS = [
    "ФИО ребёнка",
    "Дата рождения ребёнка",
    "Пол ребёнка",
    "ФИО родителя",
    "Телефон родителя",
    "Роль родителя",
]


def _xlsx_file(rows, headers=HEADERS, filename="import.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        filename,
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _mapping_dict(mapping_rows):
    return {key: current for key, _, _, current in mapping_rows}


def _run_celery_tasks_synchronously():
    """.delay() требует брокера (Redis) — в тестах обе задачи выполняются
    синхронно в процессе через apply(), без брокера и без изменения кода
    вьюх/задач (сам run_dry_run_job/run_import_job — см. tests_tasks.py)."""
    patchers = [
        mock.patch.object(
            run_dry_run_job,
            "delay",
            side_effect=lambda job_id: run_dry_run_job.apply(args=[job_id]),
        ),
        mock.patch.object(
            run_import_job, "delay", side_effect=lambda job_id: run_import_job.apply(args=[job_id])
        ),
    ]
    for patcher in patchers:
        patcher.start()
    return patchers
