"""
Файлы к заметкам (карточка родителя, ребёнка, заявки) и к чату WhatsApp.

Одни правила для всех: фото, PDF, документы, таблицы, текст и аудио — не
исполняемое; не больше пяти файлов к заметке и 10 МБ на файл. Файлы лежат
в default_storage (MEDIA_ROOT) и отдаются только через API с проверкой
центра — публичных ссылок нет.
"""

import uuid

from django.http import FileResponse

MAX_FILES = 5
MAX_BYTES = 10 * 1024 * 1024
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "heic", "webp", "gif"}
# webm — запись голосового из браузера (Chrome); m4a — из Safari.
AUDIO_EXTENSIONS = {"mp3", "ogg", "oga", "opus", "m4a", "aac", "wav", "amr", "webm"}
VIDEO_EXTENSIONS = {"mp4", "mov", "3gp"}
DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "txt", "csv"}
NOTE_EXTENSIONS = IMAGE_EXTENSIONS | DOCUMENT_EXTENSIONS | AUDIO_EXTENSIONS


def extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in (name or "") else ""


def files_error(files, *, allowed=NOTE_EXTENSIONS, max_files=MAX_FILES, max_bytes=MAX_BYTES):
    """Текст ошибки для сотрудника или пустая строка, если файлы подходят."""
    if len(files) > max_files:
        return f"Не больше {max_files} файлов за раз."
    for uploaded in files:
        if uploaded.size > max_bytes:
            return f"Файл «{uploaded.name}» больше {max_bytes // (1024 * 1024)} МБ."
        if extension(uploaded.name) not in allowed:
            return f"Файл «{uploaded.name}»: можно фото, аудио, PDF, Word, Excel и текст."
    return ""


def upload_path(folder: str, organization_id, filename: str) -> str:
    # Случайная папка: имя файла от пользователя не угадывается и не конфликтует.
    return f"{folder}/{organization_id}/{uuid.uuid4().hex}/{filename}"


def file_response(field_file, *, name: str, content_type: str):
    """Картинки, PDF, аудио и видео — открыть в браузере; остальное — скачать."""
    inline = content_type.startswith(("image/", "audio/", "video/")) or (
        content_type == "application/pdf"
    )
    return FileResponse(
        field_file.open("rb"),
        as_attachment=not inline,
        filename=name,
        content_type=content_type or "application/octet-stream",
    )
