"""
Вход родителя по одноразовому коду (TRU-135, ADR-0007).

Защита — выше, чем у входа сотрудников: это единственный вход без пароля,
и за ним данные несовершеннолетних.

- Ответ на «пришлите код» одинаков для любого номера: есть он в базе или
  нет — по форме входа нельзя проверить, ходит ли ребёнок в центр. Для
  неизвестного номера тоже создаётся запрос кода (код никуда не уходит),
  так что лимиты, ответы и время ответа совпадают; отправка — в фоне.
- Лимиты: не чаще раза в RESEND_SECONDS и не больше CODES_PER_HOUR кодов
  на номер, IP_CODES_PER_HOUR с одного IP. Считаются по таблице запросов,
  а не в кэше: одинаково на всех серверах.
- Код: 6 цифр, живёт OTP_CODE_TTL_SECONDS, одноразовый, после
  MAX_ATTEMPTS неверных вводов сгорает. Хранится только HMAC.
- Сессия: случайный токен, в базе — хэш; живёт SESSION_DAYS и
  продлевается, пока родитель заходит.
"""

import hashlib
import hmac
import secrets
import threading
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from domains.platform.core.audit import AuditLog
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.otp.senders import send_code

from . import access
from .models import OtpChallenge, ParentAccessLog, ParentAccount, ParentSession

CODE_LENGTH = 6
MAX_ATTEMPTS = 5
RESEND_SECONDS = 60
CODES_PER_HOUR = 5
IP_CODES_PER_HOUR = 20
SESSION_DAYS = 90
# Продлевать срок не чаще раза в день — не писать в базу на каждый запрос.
SESSION_TOUCH_EVERY = timedelta(days=1)

CODE_SENT = "Если номер есть в базе центра, мы отправили на него код."


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


def dispatch_code(phone: str, code: str) -> None:
    """Отправка — в фоне после ответа: время ответа не зависит от того,
    известен ли номер и сколько думал провайдер."""
    threading.Thread(target=send_code, args=(phone, code), daemon=True).start()


def request_code(raw_phone: str, request_meta: dict) -> dict:
    phone = normalize(raw_phone)
    _issue_code(
        phone,
        request_meta,
        purpose=OtpChallenge.Purpose.LOGIN,
        send=access.phone_is_known(phone),
    )
    return {
        "detail": CODE_SENT,
        "phone": phone,
        "resend_in": RESEND_SECONDS,
        "expires_in": settings.OTP_CODE_TTL_SECONDS,
    }


def _issue_code(phone, request_meta, *, purpose, send, account=None):
    """Новый код с лимитами. send=False — запрос создаётся, но код никуда
    не уходит (неизвестный номер при входе)."""
    ip = request_meta.get("ip")
    now = timezone.now()
    hour_ago = now - timedelta(hours=1)

    recent = OtpChallenge.objects.filter(phone=phone, created_at__gte=hour_ago)
    last = recent.order_by("-created_at").first()
    wait = None
    if last and (now - last.created_at).total_seconds() < RESEND_SECONDS:
        wait = RESEND_SECONDS - int((now - last.created_at).total_seconds())
    elif recent.count() >= CODES_PER_HOUR:
        oldest = recent.order_by("created_at").first()
        wait = int((oldest.created_at + timedelta(hours=1) - now).total_seconds()) + 1
    elif (
        ip
        and OtpChallenge.objects.filter(ip=ip, created_at__gte=hour_ago).count()
        >= IP_CODES_PER_HOUR
    ):
        wait = 3600
    if wait is not None:
        _log(ParentAccessLog.Event.CODE_RATE_LIMITED, phone, request_meta)
        minutes = max(1, round(wait / 60))
        message = (
            f"Новый код можно запросить через {wait} с."
            if wait < 120
            else f"Слишком много запросов. Попробуйте через {minutes} мин."
        )
        raise LoginError(message, status=429, retry_after=wait)

    code = "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))
    OtpChallenge.objects.create(
        phone=phone,
        purpose=purpose,
        account=account,
        code_hash=_hash(f"{phone}:{code}"),
        ip=ip,
        expires_at=now + timedelta(seconds=settings.OTP_CODE_TTL_SECONDS),
        channel="pending" if send else "",
    )
    _log(ParentAccessLog.Event.CODE_REQUESTED, phone, request_meta, account=account)
    if send:
        transaction.on_commit(lambda: dispatch_code(phone, code))


def verify_code(raw_phone: str, code: str, request_meta: dict) -> dict:
    """Ошибка поднимается после транзакции: счётчик попыток и запись в
    журнал должны сохраниться, иначе лимит попыток не работает."""
    phone = normalize(raw_phone)
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    with transaction.atomic():
        outcome = _check_code(phone, code, request_meta)
    if isinstance(outcome, LoginError):
        raise outcome
    return outcome


def _check_code(phone, code, request_meta):
    now = timezone.now()
    challenge = (
        OtpChallenge.objects.select_for_update()
        .filter(
            phone=phone,
            purpose=OtpChallenge.Purpose.LOGIN,
            used_at__isnull=True,
            expires_at__gt=now,
            attempts__lt=MAX_ATTEMPTS,
        )
        .order_by("-created_at")
        .first()
    )
    # Номер мог пропасть из базы, пока родитель вводил код, — тогда не пускаем.
    error = _consume(
        challenge, phone, code, request_meta, extra_ok=lambda: access.phone_is_known(phone)
    )
    if error:
        return error
    account, _ = ParentAccount.objects.get_or_create(phone=phone)
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
    _log(ParentAccessLog.Event.LOGIN, phone, request_meta, account=account)
    _audit_login(account, session)
    return {"token": token, "expires_at": session.expires_at}


def _consume(challenge, phone, code, request_meta, extra_ok=lambda: True):
    """Проверить код и погасить его. Ошибка — LoginError (не поднимается:
    вызывающий выходит из транзакции, чтобы счётчик попыток сохранился)."""
    if challenge is None:
        _log(ParentAccessLog.Event.LOGIN_FAILED, phone, request_meta)
        return LoginError("Код устарел или попыток больше нет. Запросите новый код.")
    challenge.attempts += 1
    matches = len(code) == CODE_LENGTH and hmac.compare_digest(
        challenge.code_hash, _hash(f"{phone}:{code}")
    )
    if not matches or not extra_ok():
        challenge.save(update_fields=["attempts"])
        _log(ParentAccessLog.Event.LOGIN_FAILED, phone, request_meta, account=challenge.account)
        left = MAX_ATTEMPTS - challenge.attempts
        if left <= 0:
            return LoginError("Код введён неверно слишком много раз. Запросите новый код.")
        return LoginError(f"Неверный код. Осталось попыток: {left}.")
    challenge.used_at = timezone.now()
    challenge.save(update_fields=["attempts", "used_at"])
    return None


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
