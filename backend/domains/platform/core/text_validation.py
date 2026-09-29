from django.core.exceptions import ValidationError

PERSON_NAME_PUNCTUATION = {" ", "-", "'", "’"}


def normalize_entity_name(value: str, *, max_length: int = 255) -> str:
    """Trim repeated whitespace and reject unusably short display names."""
    normalized = " ".join(value.split())
    if len(normalized) < 2:
        raise ValidationError("Введите не менее двух символов.")
    if len(normalized) > max_length:
        raise ValidationError(f"Введите не более {max_length} символов.")
    return normalized


def normalize_person_name(value: str, *, max_length: int = 255) -> str:
    """Normalize a human name and allow letters, spaces, hyphens and apostrophes."""
    normalized = normalize_entity_name(value, max_length=max_length)
    if sum(char.isalpha() for char in normalized) < 2:
        raise ValidationError("Имя должно содержать не менее двух букв.")
    if any(not char.isalpha() and char not in PERSON_NAME_PUNCTUATION for char in normalized):
        raise ValidationError("Используйте только буквы, пробел, дефис или апостроф.")
    return normalized
