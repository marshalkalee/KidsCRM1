import { t } from '../../i18n'

// Подпись роли в списке исполнителей.
export const ROLE_LABELS = {
  owner: () => t('владелец'),
  manager: () => t('управляющий'),
  admin: () => t('администратор'),
  accountant: () => t('бухгалтер'),
  teacher: () => t('преподаватель'),
}

// Кто ставит и передаёт задачи (как TASK_MANAGERS на сервере).
export const TASK_MANAGER_ROLES = ['owner', 'manager', 'admin']

// Типы, которые человек выбирает руками. «Не пришёл на пробное» и «Нет
// абонемента» создаёт только система (автоправила, TRU-108).
export const MANUAL_TYPES = [
  { value: 'call_back', get label() { return t('Перезвонить') } },
  { value: 'payment_reminder', get label() { return t('Напомнить об оплате') } },
  { value: 'trial_signup', get label() { return t('Записать на пробное') } },
  { value: 'renewal_offer', get label() { return t('Предложить продление') } },
  { value: 'other', get label() { return t('Другое') } },
]

// Все типы, как Task.Type на сервере, — для фильтра истории: в ней есть и
// задачи, созданные системой.
export const TASK_TYPES = [
  ...MANUAL_TYPES.filter(type => type.value !== 'other'),
  { value: 'trial_no_show', get label() { return t('Не пришёл на пробное') } },
  { value: 'missing_subscription', get label() { return t('Нет абонемента') } },
  { value: 'retention', get label() { return t('Удержание клиента') } },
  { value: 'parent_request', get label() { return t('Запрос родителя') } },
  { value: 'contact', get label() { return t('Связаться') } },
  ...MANUAL_TYPES.filter(type => type.value === 'other'),
]
