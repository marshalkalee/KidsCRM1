"""
Этапы воронки центра (TRU-154). Код и аналитика работают с ролью
(Lead.Status) — здесь только то, как роли называются и выглядят у центра,
и какие свои этапы центр добавил между ними.

Системные этапы заводятся у новой организации (signals.py) и миграцией
0011 — у существующих. ensure_default_stages идемпотентна и вызывается
ещё и при чтении: организация, созданная в обход сигнала (фикстуры,
loaddata), не останется без воронки.
"""

from .models import Lead, LeadKind, LeadStage

S = Lead.Status
C = LeadStage.Color

# Набор MVP — с ним центр получает ровно ту воронку, что была до TRU-154.
DEFAULT_STAGES = [
    (S.NEW, "Новая", C.BLUE),
    (S.CONTACTED, "Связались", C.RED),
    (S.TRIAL_SCHEDULED, "Записан на пробное", C.AMBER),
    (S.TRIAL_ATTENDED, "Пришёл на пробное", C.VIOLET),
    (S.PURCHASED, "Купил абонемент", C.GREEN),
    (S.THINKING, "Думает", C.GRAY),
    (S.REJECTED, "Отказ", C.PINK),
]


def ensure_default_stages(organization, stage_model=LeadStage):
    """Завести недостающие системные этапы. Модель — параметром, как в
    defaults.ensure_default_dictionaries: миграция зовёт с исторической."""
    existing = set(
        stage_model.objects.filter(organization=organization, is_system=True).values_list(
            "role", flat=True
        )
    )
    missing = [
        stage_model(
            organization=organization,
            role=role,
            name=name,
            color=color,
            order=(index + 1) * 10,
            is_system=True,
        )
        for index, (role, name, color) in enumerate(DEFAULT_STAGES)
        if role not in existing
    ]
    if missing:
        stage_model.objects.bulk_create(missing)


def org_stages(organization):
    """Все этапы центра по порядку, включая скрытые."""
    ensure_default_stages(organization)
    return list(LeadStage.objects.filter(organization=organization).order_by("order", "created_at"))


class Funnel:
    """Этапы одной организации, разобранные один раз на запрос: доска,
    список и история заявок спрашивают «какой этап у заявки» сотни раз."""

    def __init__(self, organization):
        self.stages = org_stages(organization)
        self.by_id = {stage.pk: stage for stage in self.stages}
        self.system = {stage.role: stage for stage in self.stages if stage.is_system}

    def of(self, lead) -> LeadStage:
        """Этап заявки: свой, если задан и не скрыт, иначе системный её роли."""
        stage = self.by_id.get(lead.stage_id)
        if stage is None or stage.is_hidden or stage.role != lead.status:
            return self.system[lead.status]
        return stage

    def for_change(self, change) -> LeadStage:
        """Этап, в который пришла запись истории — по ссылке, не по тексту."""
        return self.by_id.get(change.to_stage_id) or self.system[change.to_status]

    def label(self, role) -> str:
        return self.system[role].name

    def visible(self, kind=LeadKind.NEW):
        """Колонки доски: видимые этапы ролей, которые есть у вида заявки."""
        roles = Lead.statuses_for(kind)
        visible = [s for s in self.stages if not s.is_hidden and s.role in roles]
        if kind == LeadKind.RENEWAL:
            # У продлений свой порядок ролей (Lead.RENEWAL_STATUSES: «Думает»
            # перед «Продлил»); свои этапы — внутри роли в порядке центра.
            visible.sort(key=lambda s: roles.index(s.role))
        return visible

    def transitions(self, kind=LeadKind.NEW):
        """{id этапа: [id этапов]} — куда можно перенести с каждого этапа.
        Между ролями — по Lead.TRANSITIONS (правила не меняются от того, как
        центр назвал этапы); внутри роли — на любой другой её этап."""
        allowed = Lead.transitions_for(kind)
        visible = self.visible(kind)
        return {
            str(src.pk): [
                str(dst.pk)
                for dst in visible
                if dst.pk != src.pk and (dst.role == src.role or dst.role in allowed[src.role])
            ]
            for src in visible
        }
