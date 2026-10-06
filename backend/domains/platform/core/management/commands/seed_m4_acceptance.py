"""Prepare three repeatable fake parent profiles for the M4 acceptance run (TRU-149)."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from domains.people.clients.models import ChildContact, ContactPhone, ParentContact
from domains.people.portal.models import Announcement, ParentAccount
from domains.platform.tenants.models import Organization
from domains.platform.users.models import User
from domains.scheduling.groups.models import GroupMembership
from domains.scheduling.schedule.models import Lesson

PROFILES = (
    ("+77000001491", "Тестовый родитель Анна", "ru"),
    ("+77000001492", "Тестовый родитель Марат", "kk"),
    ("+77000001493", "Тестовый родитель Ольга", "ru"),
)


class Command(BaseCommand):
    help = "Создаёт три фейковых родительских профиля для приёмки M4 (только DEBUG)."

    def add_arguments(self, parser):
        parser.add_argument("--organization", default="true-ballet", help="Slug организации")

    @transaction.atomic
    def handle(self, *args, organization, **options):
        if not settings.DEBUG:
            raise CommandError("Команда доступна только при DEBUG=True.")

        org = Organization.objects.filter(slug=organization, deleted_at__isnull=True).first()
        if org is None:
            raise CommandError(f"Организация со slug={organization!r} не найдена.")

        candidates = self._candidate_memberships(org)
        if len(candidates) < len(PROFILES):
            raise CommandError(
                "Для приёмки нужны минимум три ребёнка с активной группой и будущим занятием. "
                f"Найдено: {len(candidates)}."
            )

        rows = []
        for (phone, parent_name, language), membership in zip(PROFILES, candidates, strict=True):
            parent, _ = ParentContact.objects.update_or_create(
                organization=org,
                whatsapp=phone,
                defaults={"full_name": parent_name, "email": ""},
            )
            ContactPhone.objects.update_or_create(
                parent_contact=parent,
                number=phone,
                defaults={"organization": org},
            )
            ChildContact.objects.update_or_create(
                organization=org,
                child=membership.child,
                parent_contact=parent,
                defaults={
                    "role": ChildContact.Role.OTHER,
                    "is_primary_contact": False,
                    "is_payer": False,
                },
            )
            ParentAccount.objects.update_or_create(phone=phone, defaults={"language": language})
            rows.append((phone, language, membership.child.full_name))

        owner = User.objects.filter(organization=org, role=User.Role.OWNER).first()
        if owner:
            Announcement.objects.update_or_create(
                organization=org,
                title="Демо M4: концерт",
                defaults={
                    "body": (
                        "Приглашаем родителей на отчётный концерт. "
                        "Подробности уточняйте у администратора."
                    ),
                    "status": Announcement.Status.PUBLISHED,
                    "published_at": timezone.now(),
                    "audience": Announcement.Audience.ORGANIZATION,
                    "created_by": owner,
                },
            )

        self.stdout.write(self.style.SUCCESS("Тестовые профили M4 готовы:"))
        for phone, language, child_name in rows:
            self.stdout.write(f"  {phone} · {language} · ребёнок: {child_name}")
        self.stdout.write("Вход: http://localhost/parent/login (OTP выводится в лог backend).")

    @staticmethod
    def _candidate_memberships(org):
        future_group_ids = Lesson.objects.filter(
            organization=org,
            group__isnull=False,
            starts_at__gt=timezone.now(),
            status=Lesson.Status.SCHEDULED,
            deleted_at__isnull=True,
        ).values_list("group_id", flat=True)
        memberships = (
            GroupMembership.objects.filter(
                organization=org,
                left_at__isnull=True,
                deleted_at__isnull=True,
                child__deleted_at__isnull=True,
                group_id__in=future_group_ids,
            )
            .select_related("child", "group")
            .order_by("child__full_name", "id")
        )
        unique = []
        seen = set()
        for membership in memberships:
            if membership.child_id not in seen:
                seen.add(membership.child_id)
                unique.append(membership)
            if len(unique) == len(PROFILES):
                break
        return unique
