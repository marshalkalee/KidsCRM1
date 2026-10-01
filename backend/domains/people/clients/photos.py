"""
Фото ребёнка для API frontend2 (views.child_photo_api). Файл сохраняется сразу при выборе,
до сохранения карточки: при создании ребёнка его ещё нет. В Child хранится
только ссылка (photo_url).
"""

from domains.platform.core.images import MAX_IMAGE_BYTES, save_image

MAX_PHOTO_BYTES = MAX_IMAGE_BYTES


def save_child_photo(request, uploaded) -> str:
    """Сохраняет проверенное изображение и возвращает абсолютный URL
    (URLField на Child требует схему и хост)."""
    return save_image(request, uploaded, "children/photos")
