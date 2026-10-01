"""
Тарифы (ТЗ раздел 7: «сравнение филиалов — для тарифа Network»). Биллинга
пока нет, `Organization.plan` у всех пуст — поэтому пустой тариф ничего не
ограничивает, а явно заданный тариф без функции её закрывает. Когда
появится биллинг, меняется только таблица ниже.
"""

NETWORK = "network"

# Функция → тарифы, в которые она входит.
FEATURES = {
    "branch_compare": {NETWORK},
}


def has_feature(organization, feature) -> bool:
    plan = (organization.plan or "").strip().lower()
    if not plan:
        return True
    return plan in FEATURES.get(feature, set())
