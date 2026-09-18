"""
Baseline-миграция проекта. Не создаёт таблиц — только то, что нужно всем
доменам до первой бизнес-таблицы: расширения PostgreSQL.

- pg_trgm (TrigramExtension) — быстрый поиск по частичному совпадению без
  учёта регистра (ТЗ п. 4.1: поиск по имени ребёнка/родителя/телефону).

pgcrypto не нужен: PostgreSQL 16 (наша версия, см. docker-compose.yml) имеет
gen_random_uuid() как встроенную функцию с версии 13 — расширение для этого
не требуется. UUID для PK всё равно генерируются на стороне Django
(default=uuid.uuid4), а не в БД, — см. domains/platform/core/models.py.
"""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),
    ]
