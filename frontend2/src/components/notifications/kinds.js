import { ClipboardCheck, Inbox, ListTodo, MessageCircle, MessageSquareText, Sparkles, Wallet, WalletCards } from 'lucide-react'
import { money, plural } from '../../ui'
import { t } from '../../i18n'

// Вид уведомления → иконка, заголовок, строка с числом (TRU-72).
export const NOTIFICATION_KINDS = {
  // Написали в WhatsApp центра, а с номера центра ещё не ответили.
  whatsapp_messages: {
    icon: MessageCircle,
    tone: 'bg-success-50 text-success-600',
    get title() { return t('WhatsApp') },
    text: item => (item.count > 1
      ? t('Ждут ответа: {n} · {name}: {preview}', { n: item.count, name: item.name, preview: item.preview })
      : `${item.name}: ${item.preview}`),
  },
  parent_requests: {
    icon: MessageSquareText,
    tone: 'bg-warning-50 text-warning-600',
    get title() { return t('Запросы родителей') },
    text: item => t('Ожидают решения: {n}', { n: item.count }),
  },
  new_leads: {
    icon: Inbox,
    tone: 'bg-info-50 text-info-600',
    get title() { return t('Новые заявки') },
    text: item => `${item.count} ${plural(item.count, ['заявка ждёт звонка', 'заявки ждут звонка', 'заявок ждут звонка'])}`,
  },
  unmarked_lessons: {
    icon: ClipboardCheck,
    tone: 'bg-warning-50 text-warning-600',
    get title() { return t('Посещаемость за вчера') },
    text: item => `${item.count} ${plural(item.count, ['занятие без отметки', 'занятия без отметки', 'занятий без отметки'])}`,
  },
  overdue_debts: {
    icon: Wallet,
    tone: 'bg-danger-50 text-danger-600',
    get title() { return t('Просроченные долги') },
    text: item => t('{children} · {total}, старше {days} дн.', {
      children: `${item.count} ${plural(item.count, ['ребёнок', 'ребёнка', 'детей'])}`,
      total: money(item.total),
      days: item.days,
    }),
  },
  no_subscription: {
    icon: WalletCards,
    tone: 'bg-brand-50 text-brand-600',
    get title() { return t('Без абонемента') },
    text: item => `${item.count} ${plural(item.count, ['ребёнок занимается', 'ребёнка занимаются', 'детей занимаются'])} ${t('без действующего абонемента')}`,
  },
  ai_digest: {
    icon: Sparkles,
    tone: 'bg-[linear-gradient(135deg,#ede9fe,#fce7f3)] text-[#7c3aed]',
    get title() { return t('Отчёт недели') },
    text: () => t('Готов: что сделать на этой неделе'),
  },
  overdue_tasks: {
    icon: ListTodo,
    tone: 'bg-danger-50 text-danger-600',
    get title() { return t('Просроченные задачи') },
    text: item => `${item.count} ${plural(item.count, ['просроченная задача', 'просроченные задачи', 'просроченных задач'])}`,
  },
  // Коллега написал комментарий к моей задаче (TRU-184).
  task_comments: {
    icon: MessageSquareText,
    tone: 'bg-info-50 text-info-600',
    get title() { return t('Комментарии к задачам') },
    text: item => t('Задач с новыми комментариями: {n}', { n: item.count }),
  },
}
