from .group_promotion import TEMPLATE as GROUP_PROMOTION
from .marketing_recommendations import TEMPLATE as MARKETING_RECOMMENDATIONS

TEMPLATES = {
    MARKETING_RECOMMENDATIONS.key: MARKETING_RECOMMENDATIONS,
    GROUP_PROMOTION.key: GROUP_PROMOTION,
}


def get_template(key: str):
    try:
        return TEMPLATES[key]
    except KeyError as exc:
        raise ValueError(f"Неизвестный шаблон ИИ: {key}") from exc
