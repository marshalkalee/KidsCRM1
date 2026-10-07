"""Центр рассылок родителям (TRU-168). Снаружи — только notify() и согласие."""

from .service import MessagingError, consent_status, notify, set_consent

__all__ = ["MessagingError", "consent_status", "notify", "set_consent"]
