from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    return render(request, "platform/home.html")


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
