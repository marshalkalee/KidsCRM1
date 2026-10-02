import { ArrowRight, CalendarDays, CheckSquare, Megaphone, UserRound, Wallet } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, PageHeader, cn } from '../../ui'
import { t } from '../../i18n'
import { useParent } from '../useParent'

const SECTIONS = [
  {
    to: '/parent/schedule',
    icon: CalendarDays,
    title: 'Расписание',
    description: 'Ближайшие занятия, время и место проведения.',
    iconClass: 'bg-brand-50 text-brand-600',
    cardClass: 'xl:col-span-3',
  },
  {
    to: '/parent/attendance',
    icon: CheckSquare,
    title: 'Посещения',
    description: 'История отметок, списаний и доступные отработки.',
    iconClass: 'bg-success-50 text-success-600',
    cardClass: 'xl:col-span-3',
  },
  {
    to: '/parent/subscription',
    icon: Wallet,
    title: 'Абонемент',
    description: 'Остаток занятий, срок действия и платежи.',
    iconClass: 'bg-info-50 text-info-600',
    cardClass: 'xl:col-span-2',
  },
  {
    to: '/parent/announcements',
    icon: Megaphone,
    title: 'Объявления',
    description: 'Новости центра и важные сообщения для родителей.',
    iconClass: 'bg-warning-50 text-warning-600',
    cardClass: 'xl:col-span-2',
  },
  {
    to: '/parent/profile',
    icon: UserRound,
    title: 'Профиль',
    description: 'Контакты, язык кабинета и активные устройства.',
    iconClass: 'bg-surface-muted text-ink-muted',
    cardClass: 'sm:col-span-2 xl:col-span-2',
  },
]

export default function ParentHome() {
  const { child, profile } = useParent()
  const name = profile?.full_name?.split(' ')[0]

  return (
    <div>
      <PageHeader
        title={name ? t('Здравствуйте, {name}!', { name }) : t('Кабинет родителя')}
        description={child
          ? t('Вся важная информация о занятиях ребёнка {name}.', { name: child.full_name })
          : t('Выберите ребёнка, чтобы посмотреть информацию.')}
      />

      <section aria-labelledby="parent-sections-title">
        <div className="mb-3 px-1">
          <h2 id="parent-sections-title" className="text-lg font-bold text-ink">{t('Разделы кабинета')}</h2>
          <p className="mt-0.5 text-[13px] text-ink-muted">{t('Выберите, что хотите посмотреть.')}</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          {SECTIONS.map(section => <SectionCard key={section.to} {...section} />)}
        </div>
      </section>
    </div>
  )
}

function SectionCard({ to, icon: Icon, title, description, iconClass, cardClass }) {
  return (
    <Link to={to} className={cn('group block rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2', cardClass)}>
      <Card className="flex h-full min-h-36 flex-col transition duration-200 group-hover:-translate-y-0.5 group-hover:border-brand-200 group-hover:shadow-card">
        <div className="flex items-start justify-between gap-3">
          <span className={cn('flex size-11 items-center justify-center rounded-xl', iconClass)}>
            <Icon className="size-5" />
          </span>
          <ArrowRight className="size-5 text-ink-subtle transition-transform group-hover:translate-x-1 group-hover:text-brand-600" />
        </div>
        <div className="mt-auto pt-6">
          <h3 className="text-base font-bold text-ink">{t(title)}</h3>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">{t(description)}</p>
        </div>
      </Card>
    </Link>
  )
}
