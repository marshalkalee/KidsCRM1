from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from domains.platform.core.decorators import role_required
from domains.platform.tenants.models import Branch


@role_required()
def home(request):
    return render(request, "platform/home.html", {"now": timezone.now()})


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
        if user is not None:
            login(request, user)
            next_url = request.POST.get("next") or "core:home"
            return redirect(next_url)
        error = "login.error"

    context = {"error": error, "next": request.GET.get("next", "")}
    return render(request, "platform/login.html", context)


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
        if Branch.objects.for_tenant(request.user.organization).filter(pk=branch_id).exists():
            request.session["active_branch_id"] = branch_id
    next_url = request.POST.get("next") or "core:home"
    return redirect(next_url)
