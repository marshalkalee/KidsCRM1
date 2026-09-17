"""
Единая точка правды для "какие направления сейчас можно выбрать" —
группы (Дарья), типы абонементов (Bekzat) и заявки должны звать эту
функцию вместо своего `Direction.objects.filter(is_active=True)`, иначе
легко забыть фильтр и предложить архивированное направление там, где
не надо (ТЗ, критерий приёмки: архивированное направление не предлагается
при создании новой группы, но остаётся в старых — старые группы просто
хранят свою уже выбранную Direction, активную или нет, им эта функция не нужна).
"""

from domains.platform.tenants.models import Direction


def get_selectable_directions(organization, branch=None):
    qs = Direction.objects.for_tenant(organization).filter(is_active=True)
    if branch is not None:
        qs = qs.filter(branches=branch)
    return qs.order_by("name")
