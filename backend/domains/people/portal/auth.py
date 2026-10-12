"""
Вход родителя по телефону и паролю (Д40; раньше — по коду, TRU-135).

Пароль выдаёт администратор центра в карточке родителя («Доступ в
кабинет» → «Выдать пароль»): система генерирует его, показывает один раз,
родитель меняет его в профиле. Забыл — администратор выдаёт новый, и все
прежние входы закрываются.

Защита — данные несовершеннолетних:

- Ответ на неверный вход одинаков для любого номера: по форме нельзя
  проверить, ходит ли ребёнок в центр. Для неизвестного номера пароль всё
  равно проверяется с «пустым» хэшем — время ответа одно и то же.
- Лимиты неудачных попыток: FAILED_PER_PHONE за FAILED_WINDOW на номер и
  FAILED_PER_IP за час с одного IP. Считаются по журналу входов, а не в
  кэше: одинаково на всех серверах.
- Пароль хранится только хэшем (как у сотрудников).
- Сессия: случайный токен, в базе — хэш; живёт SESSION_DAYS и
  продлевается, пока родитель заходит.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number

from . import access
from .models import ParentAccessLog, ParentAccount, ParentSession

SESSION_DAYS = 90
# Продлевать срок не чаще раза в день — не писать в базу на каждый запрос.
SESSION_TOUCH_EVERY = timedelta(days=1)
FAILED_PER_PHONE = 5
FAILED_WINDOW = timedelta(minutes=15)
FAILED_PER_IP = 20
MIN_PASSWORD = 8
# Выданный пароль — без похожих символов (0/O, 1/l/I): его диктуют и пересылают.
ISSUED_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
ISSUED_LENGTH = 10
WRONG_LOGIN = "Неверный номер или пароль."
# Хэш «ничего» — сравниваем с ним, когда аккаунта нет, чтобы время ответа совпадало.
_DUMMY_HASH = make_password(None)


class LoginError(Exception):
    """Текст — для родителя. status — HTTP-код ответа."""

    def __init__(self, message, status=400, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def normalize(raw: str) -> str:
    try:
        return normalize_phone_number(raw or "")
    except InvalidPhoneNumberError as exc:
        raise LoginError("Введите номер телефона, например +7 701 123 45 67.") from exc


def _hash(value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _log(event, phone, request_meta, account=None):
    ParentAccessLog.objects.create(
        account=account,
        phone=phone,
        event=event,
        ip=request_meta.get("ip"),
        user_agent=(request_meta.get("user_agent") or "")[:255],
    )


def _failed_recently(phone, ip) -> int | None:
    """Сколько ждать до новой попытки или None — можно пробовать."""
    now = timezone.now()
    failed = ParentAccessLog.objects.filter(event=ParentAccessLog.Event.LOGIN_FAILED)
    by_phone = failed.filter(phone=phone, created_at__gte=now - FAILED_WINDOW)
    if by_phone.count() >= FAILED_PER_PHONE:
        oldest = by_phone.order_by("created_at").first()
        return int((oldest.created_at + FAILED_WINDOW - now).total_seconds()) + 1
    hour_ago = now - timedelta(hours=1)
    if ip and failed.filter(ip=ip, created_at__gte=hour_ago).count() >= FAILED_PER_IP:
        return 3600
    return None


def login(raw_phone: str, password: str, request_meta: dict) -> dict:
    """Телефон + пароль → токен сессии. Ошибка — одна и та же для любого номера."""
    phone = normalize(raw_phone)
    wait = _failed_recently(phone, request_meta.get("ip"))
    if wait is not None:
        minutes = max(1, round(wait / 60))
        raise LoginError(
            f"Слишком много неудачных попыток. Попробуйте через {minutes} мин.",
            status=429,
            retry_after=wait,
        )
    account = ParentAccount.objects.filter(phone=phone).first()
    stored = account.password if account and account.password else _DUMMY_HASH
    matches = check_password(password or "", stored)
    # Номер мог пропасть из базы центра — тогда не пускаем, даже с верным паролем.
    if not (account and account.password and matches and access.phone_is_known(phone)):
        _log(ParentAccessLog.Event.LOGIN_FAILED, phone, request_meta, account=account)
        raise LoginError(WRONG_LOGIN, status=400)
    return _start_session(account, request_meta)


def _start_session(account, request_meta) -> dict:
    now = timezone.now()
    account.last_login_at = now
    account.save(update_fields=["last_login_at"])
    token = secrets.token_urlsafe(32)
    session = ParentSession.objects.create(
        account=account,
        token_hash=_hash(token),
        user_agent=(request_meta.get("user_agent") or "")[:255],
        ip=request_meta.get("ip"),
        expires_at=now + timedelta(days=SESSION_DAYS),
    )
    _log(ParentAccessLog.Event.LOGIN, account.phone, request_meta, account=account)
    _audit_login(account, session)
    return {"token": token, "expires_at": session.expires_at}


def _set_password(account, password):
    account.password = make_password(password)
    account.password_set_at = timezone.now()
    account.save(update_fields=["password", "password_set_at"])


@transaction.atomic
def issue_password(raw_phone: str) -> str:
    """Новый пароль для номера родителя (выдаёт администратор). Прежние входы
    закрываются: выдают новый, когда пароль забыли или он попал не туда."""
    phone = normalize(raw_phone)
    if not access.phone_is_known(phone):
        raise LoginError("У этого номера нет детей в центре — кабинет ему не нужен.")
    password = "".join(secrets.choice(ISSUED_ALPHABET) for _ in range(ISSUED_LENGTH))
    account, _ = ParentAccount.objects.get_or_create(phone=phone)
    _set_password(account, password)
    ParentSession.objects.filter(account=account, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    return password


@transaction.atomic
def change_password(session, current: str, new: str, request_meta: dict) -> None:
    """Родитель меняет пароль сам: нужен текущий. Остальные устройства выходят."""
    account = session.account
    if not check_password(current or "", account.password or _DUMMY_HASH):
        _log(ParentAccessLog.Event.LOGIN_FAILED, account.phone, request_meta, account=account)
        raise LoginError("Текущий пароль неверный.")
    new = new or ""
    if len(new) < MIN_PASSWORD:
        raise LoginError(f"Новый пароль — не короче {MIN_PASSWORD} символов.")
    if new == current:
        raise LoginError("Новый пароль совпадает с текущим.")
    _set_password(account, new)
    ParentSession.objects.filter(account=account, revoked_at__isnull=True).exclude(
        pk=session.pk
    ).update(revoked_at=timezone.now())
    _log(ParentAccessLog.Event.PASSWORD_CHANGED, account.phone, request_meta, account=account)


def has_password(raw_phone: str) -> bool:
    try:
        phone = normalize(raw_phone)
    except LoginError:
        return False
    return ParentAccount.objects.filter(phone=phone).exclude(password="").exists()


def _audit_login(account, session):
    """Сотрудники центра видят входы родителей в своём журнале действий —
    по записи на каждую организацию, где у родителя есть дети."""
    seen = set()
    for contact in access.contacts_for_phone(account.phone).select_related("organization"):
        if contact.organization_id in seen:
            continue
        seen.add(contact.organization_id)
        AuditLog.record(
            actor=None,
            action=AuditLog.Action.PARENT_LOGIN,
            entity=contact,
            after={"session": str(session.pk), "user_agent": session.user_agent[:120]},
        )


def session_for_token(token: str):
    if not token:
        return None
    now = timezone.now()
    session = (
        ParentSession.objects.select_related("account")
        .filter(token_hash=_hash(token), revoked_at__isnull=True, expires_at__gt=now)
        .first()
    )
    if session and now - session.last_seen_at > SESSION_TOUCH_EVERY:
        session.last_seen_at = now
        session.expires_at = now + timedelta(days=SESSION_DAYS)
        session.save(update_fields=["last_seen_at", "expires_at"])
    return session


def logout(session, request_meta, everywhere=False):
    now = timezone.now()
    if everywhere:
        ParentSession.objects.filter(account=session.account, revoked_at__isnull=True).update(
            revoked_at=now
        )
        event = ParentAccessLog.Event.LOGOUT_ALL
    else:
        session.revoked_at = now
        session.save(update_fields=["revoked_at"])
        event = ParentAccessLog.Event.LOGOUT
    _log(event, session.account.phone, request_meta, account=session.account)
