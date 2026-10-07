"""
Тарифы (ТЗ раздел 7: «сравнение филиалов — для тарифа Network»). Биллинга
пока нет, `Organization.plan` у всех пуст — поэтому пустой тариф ничего не
ограничивает, а явно заданный тариф без функции её закрывает. Когда
появится биллинг, меняется только таблица ниже.
"""

NETWORK = "network"
ENTERPRISE = "enterprise"

# Функция → тарифы, в которые она входит.
FEATURES = {
    "branch_compare": {NETWORK, ENTERPRISE},
    "public_api": {ENTERPRISE},
}
# Функции, которые без явного тарифа закрыты (пустой тариф их не открывает):
# публичное API — обязательство перед чужим кодом и площадь атаки (TRU-176).
STRICT_FEATURES = {"public_api"}


def has_feature(organization, feature) -> bool:
    plan = (organization.plan or "").strip().lower()
    if not plan:
        return feature not in STRICT_FEATURES
    return plan in FEATURES.get(feature, set())
