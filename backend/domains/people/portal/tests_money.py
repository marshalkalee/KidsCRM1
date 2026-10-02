"""
Абонемент и оплаты в кабинете (TRU-139): журнал списаний совпадает с
остатком у администратора и привязан к занятиям; служебное не уходит
родителю (комментарии, цена до скидки, отменённые оплаты); чужое — 404.
"""

from datetime import date, timedelta

from django.utils import timezone

from domains.money.payments.models import Payment
from domains.money.payments.services import cancel_payment
from domains.money.subscriptions.models import Subscription, SubscriptionLedgerEntry
from domains.money.subscriptions.sales import sell_subscription
from domains.money.subscriptions.subscription_service import SubscriptionService
from domains.money.subscriptions.subscription_types import create_type
from domains.money.subscriptions.subscriptions import add_ledger_entry
from domains.platform.tenants.models import Branch, Direction
from domains.platform.users.models import User
from domains.scheduling.groups.models import Group, GroupMembership
from domains.scheduling.schedule.models import Lesson

from .tests_auth import PortalAuthBase, family


class ParentMoneyTests(PortalAuthBase):
    def setUp(self):
        super().setUp()
        self.branch = Branch.objects.create(
            organization=self.org, name="Абая", phone="+77272001122"
        )
        self.ballet = Direction.objects.create(organization=self.org, name="Балет")
        self.admin = User.objects.create_user(
            phone="+77010000057",
            password="x",
            full_name="Админ",
            organization=self.org,
            role=User.Role.ADMIN,
        )
        self.group = Group.objects.create(
            organization=self.org,
            branch=self.branch,
            direction=self.ballet,
            name="Балет 4–9",
            capacity=12,
        )
        GroupMembership.objects.create(
            organization=self.org, child=self.child, group=self.group, joined_at=date(2026, 9, 1)
        )
        version = create_type(
            self.org,
            name="8 занятий",
            price=30000,
            quota_sessions=8,
            duration_days=30,
            directions=[self.ballet],
        ).versions.latest()
        self.subscription, _ = sell_subscription(
            actor=self.admin,
            child=self.child,
            subscription_type_version=version,
            direction=self.ballet,
            branch=self.branch,
            starts_on=date.today(),
            discount_amount=5000,
            discount_reason="sibling",
            discount_comment="вторая дочь, внутренняя скидка",
            paid_amount=10000,
            payment_method="cash",
        )
        self.client = self.as_parent(self.login())

    def lesson(self, days_ago):
        starts = timezone.now() - timedelta(days=days_ago)
        return Lesson.objects.create(
            organization=self.org,
            group=self.group,
            starts_at=starts,
            ends_at=starts + timedelta(hours=1),
        )

    def money(self, child=None):
        return self.client.get(f"/api/v1/portal/children/{(child or self.child).id}/money/")

    def test_ledger_explains_balance_with_lessons(self):
        first, second = self.lesson(3), self.lesson(1)
        SubscriptionService.consume(self.child.id, first.id, self.ballet.id)
        SubscriptionService.consume(self.child.id, second.id, self.ballet.id)
        SubscriptionService.revert(self.child.id, second.id)  # отметку сняли
        data = self.money().data
        cached = Subscription.objects.get().sessions_remaining_cache
        self.assertEqual(data["current"]["sessions_remaining"], cached)
        self.assertEqual(data["ledger"][0]["balance"], cached)  # последняя строка = остаток
        labels = [(r["label"], r["delta"]) for r in reversed(data["ledger"])]
        self.assertEqual(
            labels,
            [("Покупка абонемента", 8), ("Занятие", -1), ("Занятие", -1), ("Возврат занятия", 1)],
        )
        consumed = [r for r in data["ledger"] if r["label"] == "Занятие"]
        self.assertEqual({r["lesson"]["group"] for r in consumed}, {"Балет 4–9"})
        self.assertEqual([r["reverted"] for r in consumed], [True, False])

    def test_staff_details_are_hidden(self):
        add_ledger_entry(
            self.subscription,
            kind=SubscriptionLedgerEntry.Kind.MANUAL_ADJUSTMENT,
            delta=-1,
            comment="ошибка админа Айнур",
        )
        body = self.money().content.decode()
        self.assertNotIn("ошибка админа", body)
        self.assertNotIn("внутренняя скидка", body)
        self.assertNotIn("sibling", body)
        data = self.money().data
        self.assertEqual(data["current"]["price"], str(self.subscription.price))  # итоговая цена
        self.assertNotIn("list_price", data["current"])

    def test_cancelled_payments_are_hidden_and_to_pay_matches(self):
        payment = Payment.objects.get()
        cancel_payment(payment, actor=self.admin, reason="ошиблись суммой")
        data = self.money().data
        self.assertEqual(data["payments"], [])
        self.assertEqual(data["to_pay"], str(self.subscription.price))

    def test_how_to_pay_contacts_and_kaspi(self):
        self.org.settings = {"kaspi_payment_details": "https://pay.kaspi.kz/pay/tb"}
        self.org.save()
        how = self.money().data["how_to_pay"]
        self.assertEqual(how["kaspi"], "https://pay.kaspi.kz/pay/tb")
        self.assertEqual(
            how["contacts"],
            [
                {
                    "branch": "Абая",
                    "phone": "+77272001122",
                    "whatsapp_url": "https://wa.me/77272001122",
                }
            ],
        )

    def test_foreign_child_money_is_404(self):
        _, (stranger,) = family(self.org, "Чужая мама", "+77019990000", "Чужой Ребёнок")
        self.assertEqual(self.money(stranger).status_code, 404)
