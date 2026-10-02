"""
Загруженные картинки (фото ребёнка, фото сотрудника): проверка, сохранение
в default_storage, удаление своего файла по ссылке. В моделях хранится
только абсолютная ссылка (URLField).
"""

import uuid
from pathlib import Path
from urllib.parse import urlparse

from django import forms
from django.conf import settings
from django.core.files.storage import default_storage

# Как подсказка в формах: «JPG, PNG до 5 МБ».
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class _ImageForm(forms.Form):
    # Pillow проверяет, что это настоящая картинка, а не файл с чужим расширением.
    file = forms.ImageField()


def clean_image(files):
    """Файл из request.FILES["file"] или текст ошибки для поля file."""
    uploaded = files.get("file")
    if uploaded is not None and uploaded.size > MAX_IMAGE_BYTES:
        return None, "Файл больше 5 МБ."
    form = _ImageForm(files=files)
    if not form.is_valid():
        return None, "Загрузите изображение: JPG или PNG."
    return form.cleaned_data["file"], None


def save_image(request, uploaded, folder: str) -> str:
    """Сохраняет картинку под случайным именем и возвращает абсолютный URL."""
    extension = Path(uploaded.name).suffix.lower()
    saved_path = default_storage.save(f"{folder}/{uuid.uuid4()}{extension}", uploaded)
    return request.build_absolute_uri(default_storage.url(saved_path))


def delete_image(url: str, folder: str) -> None:
    """Удаляет файл по ссылке, если он наш и лежит в folder (чужие ссылки не трогаем)."""
    prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
    path = urlparse(url or "").path
    if not path.startswith(f"{prefix}{folder}/"):
        return
    name = path[len(prefix) :]
    if ".." not in name and default_storage.exists(name):
        default_storage.delete(name)
