import secrets

from django.contrib.auth import authenticate, login, logout
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from domains.platform.core.context_processors import LANGUAGES
from domains.platform.core.decorators import role_required
from domains.platform.core.phone import InvalidPhoneNumberError, normalize_phone_number
from domains.platform.tenants import onboarding
from domains.platform.tenants.models import Branch


@role_required()
def home(request):
    # Прогресс настройки центра — только владельцу (мастер — его экран),
    # пока настройка не завершена (ТЗ п. 10.4).
    onboarding_progress = None
    if request.user.role == "owner":
        onboarding_progress = onboarding.progress(request.user.organization)
    return render(
        request,
        "platform/home.html",
        {"now": timezone.now(), "onboarding_progress": onboarding_progress},
    )


@role_required()
def components_demo(request):
    """
    Витрина библиотеки компонентов (таблица/форма/модалка/тосты/поиск/
    пикер) с примерами использования — см. static/site/js/components/.
    Не доменный экран, поэтому не в сайдбаре (см. комментарий в
    includes/sidebar.html): открывается прямой ссылкой при разработке/QA.
    """
    return render(request, "dev/components.html")


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Обычная Django-сессия для страниц — отдельно от JWT для API
    (см. docstring core/decorators.py). Тот же User, тот же пароль.
    """
    if request.user.is_authenticated:
        return redirect("core:home")

    error = None
    if request.method == "POST":
        phone = request.POST.get("phone", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=phone, password=password)
        if user is None:
            # Телефон при регистрации сохраняется нормализованным (+7XXXXXXXXXX),
            # а вводят его как привыкли — «8 701 …».
            try:
                normalized = normalize_phone_number(phone)
            except InvalidPhoneNumberError:
                normalized = None
            if normalized and normalized != phone:
                user = authenticate(request, username=normalized, password=password)
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or "core:home"
            return redirect(next_url)
        error = "login.error"

    context = {"error": error, "next": request.GET.get("next", "")}
    return render(request, "platform/login.html", context)


def _unique_org_slug(name: str) -> str:
    # slug — технический идентификатор организации (в API), владелец его не
    # вводит: кириллица в slugify даёт пустую строку, поэтому суффикс всегда.
    base = slugify(name)[:80] or "center"
    return f"{base}-{secrets.token_hex(3)}"


SIGNUP_FIELDS = ("org_name", "full_name", "phone")


@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def signup_view(request):
    """
    Регистрация новой организации с сайта (ТЗ п. 10.4: «от регистрации до
    первой группы без обращения к разработчику»). Тот же путь записи, что у
    API /auth/register/ (OrganizationRegisterSerializer), — организация +
    владелец, затем сразу вход и мастер онбординга.
    """
    # Локальный импорт: core не зависит от users на уровне модуля.
    from domains.platform.users.serializers import OrganizationRegisterSerializer

    if request.user.is_authenticated:
        return redirect("core:home")

    values = {}
    errors = {}
    if request.method == "POST":
        values = {field: request.POST.get(field, "").strip() for field in SIGNUP_FIELDS}
        serializer = OrganizationRegisterSerializer(
            data={
                **values,
                "org_slug": _unique_org_slug(values["org_name"]),
                "password": request.POST.get("password", ""),
            }
        )
        if serializer.is_valid():
            _org, user = serializer.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("tenants_web:onboarding")
        errors = {field: messages[0] for field, messages in serializer.errors.items()}

    return render(request, "platform/signup.html", {"values": values, "errors": errors})


@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect("core:login")


@require_http_methods(["POST"])
def switch_branch(request):
    """
    Переключатель филиала в шапке — реальные данные, не заглушка: филиал
    должен принадлежать организации текущего пользователя, выбор хранится
    в сессии (не в cookie/localStorage — сессия уже защищена CSRF/httponly).
    """
    if request.user.is_authenticated and request.user.organization_id:
        branch_id = request.POST.get("branch_id")
        # is_active=True — иначе можно было бы выбрать активным архивированный
        # филиал напрямую POST'ом, минуя то, что его убрали из списка выбора.
        if (
            Branch.objects.for_tenant(request.user.organization)
            .filter(pk=branch_id, is_active=True)
            .exists()
        ):
            request.session["active_branch_id"] = branch_id
    next_url = request.POST.get("next") or "core:home"
    return redirect(next_url)


@require_http_methods(["POST"])
def switch_language(request):
    """Переключатель языка в шапке — та же схема хранения, что у филиала
    (сессия), см. context_processors.language()."""
    lang = request.POST.get("lang")
    if lang in dict(LANGUAGES):
        request.session["lang"] = lang
    next_url = request.POST.get("next") or "core:home"
    return redirect(next_url)


def healthz(request):
    """
    Проверка живости для мониторинга (staging/прод) — не для бизнес-логики.
    Проверяет реальное соединение с БД, а не просто "процесс жив".
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:
        return JsonResponse({"status": "error", "detail": str(exc)}, status=503)
    return JsonResponse({"status": "ok"})
