"""
Веб-страницы мастера онбординга (ТЗ п. 10.4), маршрут и состояние — в
onboarding.py. Ни одна страница мастера не пишет данные своим путём:
шаги «Филиал»/«Направления»/«Группы» открывают в модалке те же формы и
вьюхи, что обычные экраны настроек (formModal → branch-create и т.д.),
шаг «Организация» — та же OrganizationSettingsForm с её save(), шаг
«Импорт» ведёт на обычный экран импорта.
"""

from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.tenants import onboarding
from domains.platform.tenants.forms import OrganizationSettingsForm
from domains.platform.tenants.models import Branch, Direction
from domains.platform.tenants.onboarding import Step

OWNER = "owner"

# Экран типов абонементов (домен Bekzat'а) пока не сделан. Когда появится —
# вписать имя маршрута сюда (например "subscriptions_web:type-create"), и
# шаг сам начнёт открывать его форму вместо заглушки.
SUBSCRIPTION_TYPE_CREATE_URL_NAME = None

STEP_TITLES = {
    Step.ORGANIZATION: "Организация",
    Step.BRANCH: "Филиал",
    Step.DIRECTIONS: "Направления",
    Step.SUBSCRIPTION_TYPES: "Типы абонементов",
    Step.GROUPS: "Группы",
    Step.IMPORT: "Импорт базы",
}


def _url_or_none(name, *args):
    if not name:
        return None
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return None


def _step_items(organization, key):
    """Что уже заведено на этом шаге — показываем, чтобы было видно результат."""
    if key == Step.BRANCH:
        return [b.name for b in Branch.objects.for_tenant(organization).order_by("name")]
    if key == Step.DIRECTIONS:
        return [d.name for d in Direction.objects.for_tenant(organization).order_by("name")]
    if key == Step.SUBSCRIPTION_TYPES:
        from domains.money.subscriptions.models import SubscriptionType

        return [t.name for t in SubscriptionType.objects.for_tenant(organization).order_by("name")]
    if key == Step.GROUPS:
        from domains.scheduling.groups.models import Group

        return [g.name for g in Group.objects.for_tenant(organization).order_by("name")]
    return []


def _step_context(request, key, form=None):
    organization = request.user.organization
    steps = onboarding.get_steps(organization)
    state = next(step for step in steps if step.key == key)
    context = {
        "step": key,
        "step_title": STEP_TITLES[key],
        "step_state": state,
        "steps": [
            {
                "key": step.key,
                "title": STEP_TITLES[step.key],
                "status": step.status,
                "number": index,
                "url": reverse("tenants_web:onboarding-step", args=[step.key]),
            }
            for index, step in enumerate(steps, start=1)
        ],
        "items": _step_items(organization, key),
        "previous_step": onboarding.previous_step_before(key),
        "next_step": onboarding.next_step_after(key),
        "form": form,
    }
    if key == Step.BRANCH:
        context["create_url"] = reverse("tenants_web:branch-create")
    elif key == Step.DIRECTIONS:
        context["create_url"] = reverse("tenants_web:direction-create")
    elif key == Step.SUBSCRIPTION_TYPES:
        context["create_url"] = _url_or_none(SUBSCRIPTION_TYPE_CREATE_URL_NAME)
    elif key == Step.GROUPS:
        context["create_url"] = _url_or_none("scheduling_web:group-create")
        # Группе нужны филиал и направление — без них форма не сохранится.
        context["missing_for_groups"] = [
            STEP_TITLES[s.key]
            for s in steps
            if s.key in (Step.BRANCH, Step.DIRECTIONS) and not s.done
        ]
    elif key == Step.IMPORT:
        context["import_url"] = reverse("clients_web:child-import-upload")
    return context


def _go_to_next(organization):
    step = onboarding.current_step(organization)
    if step:
        return redirect("tenants_web:onboarding-step", step=step)
    return redirect("tenants_web:onboarding-done")


@role_required(OWNER)
def onboarding_start(request):
    """Продолжить с того же места: первый не пройденный и не пропущенный шаг."""
    return _go_to_next(request.user.organization)


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def onboarding_step(request, step):
    if step not in onboarding.STEP_ORDER:
        raise Http404
    organization = request.user.organization
    form = None
    if step == Step.ORGANIZATION:
        if request.method == "POST":
            form = OrganizationSettingsForm(request.POST)
            if form.is_valid():
                form.save(organization)
                onboarding.confirm_organization(organization)
                return _go_to_next(organization)
        else:
            form = OrganizationSettingsForm.for_organization(organization)
    elif request.method == "POST":
        # «Далее» на шаге, который уже пройден по данным.
        return _go_to_next(organization)
    return render(request, "tenants/onboarding_step.html", _step_context(request, step, form))


@role_required(OWNER)
@require_http_methods(["POST"])
def onboarding_skip(request, step):
    if step not in onboarding.STEP_ORDER:
        raise Http404
    onboarding.skip_step(request.user.organization, step)
    return _go_to_next(request.user.organization)


@role_required(OWNER)
def onboarding_done(request):
    organization = request.user.organization
    steps = onboarding.get_steps(organization)
    return render(
        request,
        "tenants/onboarding_done.html",
        {
            "skipped_steps": [
                {
                    "title": STEP_TITLES[step.key],
                    "url": reverse("tenants_web:onboarding-step", args=[step.key]),
                }
                for step in steps
                if step.status == "skipped"
            ],
        },
    )


@role_required(OWNER)
@require_http_methods(["POST"])
def onboarding_finish(request):
    onboarding.finish(request.user.organization)
    return redirect("core:home")
