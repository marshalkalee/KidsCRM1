"""
Кастомная модель пользователя — заводится сейчас, до первой миграции,
именно чтобы не переезжать с auth.User позже (дорогая операция задним
числом).

Не наследует django.contrib.auth.models.AbstractUser: согласованная схема
(backend/docs/db-schema-v1) описывает сотрудника как `full_name` + `phone`,
без `username`/`email`/`first_name`/`last_name` — поэтому база здесь
AbstractBaseUser + PermissionsMixin (низкоуровневые классы Django для
кастомной схемы полей), а не AbstractUser.

Расхождение с db-schema-v1, которое стоит свести: там у User одна
nullable-связь `branch_id` (null = доступ ко всем филиалам). Формулировка
этой задачи и ТЗ раздел 2 ("Управляющий — один или несколько филиалов")
требуют именно нескольких конкретных филиалов, не только «один» либо
«все» — поэтому здесь `branches` (ManyToMany), а не одиночный `branch`.
Гранулярные права по ролям — отдельная задача (RBAC).
"""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, phone, password=None, **extra_fields):
        if not phone:
            raise ValueError("Телефон обязателен")
        user = self.model(phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(phone, password, **extra_fields)

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        OWNER = "owner", "Владелец"
        MANAGER = "manager", "Управляющий"
        ADMIN = "admin", "Администратор"
        TEACHER = "teacher", "Преподаватель"
        ACCOUNTANT = "accountant", "Бухгалтер"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Null допустим только для платформенных суперпользователей AEM Solutions
    # (например, через createsuperuser) — обычный сотрудник тенанта обязан
    # иметь organization; это проверяется на уровне API
    # (IsStaffOfOrganization), не на уровне БД, чтобы не блокировать
    # createsuperuser.
    organization = models.ForeignKey(
        "tenants.Organization",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    branches = models.ManyToManyField("tenants.Branch", related_name="staff", blank=True)

    full_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=20, unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone})"

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(using=using, update_fields=["deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)
