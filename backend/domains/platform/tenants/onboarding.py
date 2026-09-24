"""
Мастер онбординга новой организации (ТЗ п. 10.4): маршрут
организация → филиал → направления → типы абонементов → группы → импорт базы.

Мастер ничего не пишет сам — каждый шаг открывает тот же экран/форму, что
и обычные настройки (форма филиала, направления, группы, импорт), поэтому
изменение в мастере ничем не отличается от изменения в настройках: один
путь записи. Здесь — только маршрут и состояние.

Шаг считается пройденным по ДАННЫМ (есть филиал — шаг «Филиал» пройден),
а не по флажку: филиал, заведённый в обычных настройках мимо мастера, тоже
засчитывается. Флажки хранятся только для того, чего по данным не понять:
пропущенные шаги («вернусь позже»), подтверждение шага «Организация» (у
неё всегда есть значения по умолчанию) и «настройка завершена».
Хранилище — Organization.settings["onboarding"], рядом с порогами
автостатусов (org_settings.py).
"""

from dataclasses import dataclass

from .models import Branch, Direction, Organization
from .org_settings import DEFAULT_ORG_SETTINGS

ONBOARDING_KEY = "onboarding"


class Step:
    ORGANIZATION = "organization"
    BRANCH = "branch"
    DIRECTIONS = "directions"
    SUBSCRIPTION_TYPES = "subscription_types"
    GROUPS = "groups"
    IMPORT = "import"


# Порядок — маршрут из ТЗ п. 10.4 (организация — нулевой шаг: часовой пояс
# и пороги со значениями по умолчанию, достаточно подтвердить).
STEP_ORDER = [
    Step.ORGANIZATION,
    Step.BRANCH,
    Step.DIRECTIONS,
    Step.SUBSCRIPTION_TYPES,
    Step.GROUPS,
    Step.IMPORT,
]


@dataclass
class StepState:
    key: str
    done: bool
    skipped: bool

    @property
    def status(self) -> str:
        if self.done:
            return "done"
        if self.skipped:
            return "skipped"
        return "todo"


def _state(organization: Organization) -> dict:
    return dict((organization.settings or {}).get(ONBOARDING_KEY) or {})


def _save_state(organization: Organization, state: dict) -> None:
    # Остальные ключи settings (пороги автостатусов) не трогаем.
    organization.settings = {**(organization.settings or {}), ONBOARDING_KEY: state}
    organization.save(update_fields=["settings"])


def _organization_done(organization: Organization, state: dict) -> bool:
    # Сохранение экрана «Настройки организации» мимо мастера — тоже
    # подтверждение: форма пишет пороги в settings.
    settings = organization.settings or {}
    return bool(state.get("organization_confirmed")) or any(
        key in settings for key in DEFAULT_ORG_SETTINGS
    )


def _import_done(organization: Organization) -> bool:
    from domains.people.clients.models import ImportJob

    return (
        ImportJob.objects.for_tenant(organization)
        .filter(
            job_type=ImportJob.JobType.EXECUTE,
            status=ImportJob.Status.DONE,
            rolled_back_at__isnull=True,
        )
        .exists()
    )


def _step_done(organization: Organization, key: str, state: dict) -> bool:
    # Локальные импорты — чужие домены (groups — Дарья, subscriptions —
    # Bekzat, clients — импорт), tenants не держит их на уровне модуля.
    if key == Step.ORGANIZATION:
        return _organization_done(organization, state)
    if key == Step.BRANCH:
        return Branch.objects.for_tenant(organization).exists()
    if key == Step.DIRECTIONS:
        return Direction.objects.for_tenant(organization).exists()
    if key == Step.SUBSCRIPTION_TYPES:
        from domains.money.subscriptions.models import SubscriptionType

        return SubscriptionType.objects.for_tenant(organization).exists()
    if key == Step.GROUPS:
        from domains.scheduling.groups.models import Group

        return Group.objects.for_tenant(organization).exists()
    if key == Step.IMPORT:
        return _import_done(organization)
    raise ValueError(f"Неизвестный шаг онбординга: {key}")


def get_steps(organization: Organization) -> list[StepState]:
    state = _state(organization)
    skipped = set(state.get("skipped") or [])
    return [
        StepState(
            key=key,
            done=_step_done(organization, key, state),
            skipped=key in skipped,
        )
        for key in STEP_ORDER
    ]


def current_step(organization: Organization) -> str | None:
    """Первый шаг, который не пройден и не пропущен, — отсюда мастер
    продолжается. None — идти некуда (всё пройдено или пропущено)."""
    for step in get_steps(organization):
        if step.status == "todo":
            return step.key
    return None


def next_step_after(key: str) -> str | None:
    index = STEP_ORDER.index(key)
    return STEP_ORDER[index + 1] if index + 1 < len(STEP_ORDER) else None


def previous_step_before(key: str) -> str | None:
    index = STEP_ORDER.index(key)
    return STEP_ORDER[index - 1] if index > 0 else None


def skip_step(organization: Organization, key: str) -> None:
    state = _state(organization)
    skipped = list(state.get("skipped") or [])
    if key not in skipped:
        skipped.append(key)
    state["skipped"] = skipped
    _save_state(organization, state)


def confirm_organization(organization: Organization) -> None:
    state = _state(organization)
    state["organization_confirmed"] = True
    _save_state(organization, state)


def finish(organization: Organization) -> None:
    state = _state(organization)
    state["finished"] = True
    _save_state(organization, state)


def is_finished(organization: Organization) -> bool:
    return bool(_state(organization).get("finished"))


@dataclass
class Progress:
    done: int
    total: int
    steps: list[StepState]

    @property
    def percent(self) -> int:
        return round(self.done * 100 / self.total) if self.total else 100


def progress(organization: Organization) -> Progress | None:
    """Для карточки на главной: None — настройка завершена, показывать нечего."""
    if is_finished(organization):
        return None
    steps = get_steps(organization)
    done = sum(1 for step in steps if step.done)
    if done == len(steps):
        return None
    return Progress(done=done, total=len(steps), steps=steps)
