import { t } from '../../i18n'

// Типы, которые человек выбирает руками. «Не пришёл на пробное» и «Нет
// абонемента» создаёт только система (автоправила, TRU-108).
export const MANUAL_TYPES = [
  { value: 'call_back', get label() { return t('Перезвонить') } },
  { value: 'payment_reminder', get label() { return t('Напомнить об оплате') } },
  { value: 'trial_signup', get label() { return t('Записать на пробное') } },
  { value: 'renewal_offer', get label() { return t('Предложить продление') } },
  { value: 'other', get label() { return t('Другое') } },
]
