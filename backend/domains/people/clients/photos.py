"""
Фото ребёнка — одна реализация для старого веба (web_views.child_photo_upload)
и API frontend2 (views.child_photo_api). Файл сохраняется сразу при выборе,
до сохранения карточки: при создании ребёнка его ещё нет. В Child хранится
только ссылка (photo_url).
"""

import uuid
from pathlib import Path

from django.core.files.storage import default_storage

# Как подсказка в форме: «JPG, PNG до 5 МБ».
MAX_PHOTO_BYTES = 5 * 1024 * 1024


def save_child_photo(request, uploaded) -> str:
    """Сохраняет проверенное изображение и возвращает абсолютный URL
    (URLField на Child требует схему и хост)."""
    extension = Path(uploaded.name).suffix.lower()
    saved_path = default_storage.save(f"children/photos/{uuid.uuid4()}{extension}", uploaded)
    return request.build_absolute_uri(default_storage.url(saved_path))
