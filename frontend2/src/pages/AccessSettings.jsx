import { useEffect, useState } from 'react'
import { GraduationCap, Sparkles, UserCog } from 'lucide-react'
import api from '../api/axios'
import { Card, CardHeader, Checkbox, ErrorState, PageHeader, Skeleton, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

// Что владелец может открыть роли сверх обычного (TRU-153, backend:
// tenants/org_settings.ACCESS_SETTINGS). Проверка — на сервере, в API и
// выгрузках; здесь только переключатели и честный текст, что изменится.
const SECTIONS = [
  {
    icon: GraduationCap,
    get title() { return t('Преподаватели') },
    get description() { return t('По умолчанию преподаватель видит детей и расписание, но не контакты родителей и не деньги.') },
    items: [
      {
        key: 'teacher_sees_parent_phones',
        get label() { return t('Видят телефоны родителей') },
        get hint() { return t('Телефоны и WhatsApp в карточках детей и родителей, список обзвона при переносе занятия.') },
      },
      {
        key: 'teacher_sees_finances',
        get label() { return t('Видят абонементы, оплаты и долги') },
        get hint() { return t('Только просмотр: продавать абонементы, принимать оплату и замораживать по-прежнему не смогут. Финансовые отчёты центра остаются закрыты.') },
      },
    ],
  },
  {
    icon: UserCog,
    get title() { return t('Администраторы') },
    get description() { return t('По умолчанию у администратора рабочие списки, но не аналитика центра.') },
    items: [
      {
        key: 'admin_sees_org_summary',
        get label() { return t('Видят аналитику') },
        get hint() { return t('Раздел «Аналитика»: выручка, посещаемость, воронка — только по филиалам, где работает администратор.') },
      },
    ],
  },
  {
    // ADR-0008: эти функции отправляют внешнему ИИ то, что загрузил сотрудник,
    // как есть — имена в них метками не заменить, поэтому включает центр.
    icon: Sparkles,
    get title() { return t('ИИ-помощник') },
    get description() { return t('Имена детей и родителей уходят во внешний ИИ-сервис только метками. Две функции ниже отправляют фото или файл как есть — включайте, если центр согласен.') },
    items: [
      {
        key: 'ai_attendance_photo_enabled',
        get label() { return t('Отметка посещаемости по фото журнала') },
        get hint() { return t('Фото бумажного журнала с именами детей уходит во внешний ИИ-сервис, чтобы распознать отметки.') },
      },
      {
        key: 'ai_import_clean_enabled',
        get label() { return t('Приведение файла клиентов в порядок при импорте') },
        get hint() { return t('Загруженный файл с ФИО, датами рождения и телефонами уходит во внешний ИИ-сервис целиком.') },
      },
    ],
  },
]

/** Доступ сотрудников (TRU-153) — только владелец. Каждое переключение
 * сохраняется сразу и попадает в журнал действий. */
export default function AccessSettings() {
  const toast = useToast()
  const [values, setValues] = useState(null)
  const [error, setError] = useState(false)
  const [saving, setSaving] = useState(null)

  const fetchValues = () => api.get('organization/access/').then(res => setValues(res.data)).catch(() => setError(true))
  useEffect(() => { fetchValues() }, [])
  const load = () => {
    setError(false)
    fetchValues()
  }

  async function toggle(key, checked) {
    setSaving(key)
    try {
      const res = await api.put('organization/access/', { [key]: checked })
      setValues(res.data)
      toast.success(checked ? t('Доступ открыт') : t('Доступ закрыт'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSaving(null)
    }
  }

  return (
    <div>
      <PageHeader back={{ to: '/settings/staff', label: t('Сотрудники') }} title={t('Доступ сотрудников')} description={t('Что видят роли сверх обычного. Изменения действуют сразу и записываются в журнал действий.')} />
      {error ? (
        <Card><ErrorState onRetry={load} /></Card>
      ) : values === null ? (
        <Skeleton className="h-64" />
      ) : (
        <div className="space-y-4">
          {SECTIONS.map(section => (
            <Card key={section.title}>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 hidden rounded-lg bg-surface-muted p-2 text-ink-muted sm:block">
                  <section.icon size={18} />
                </span>
                <div className="min-w-0 flex-1">
                  <CardHeader title={section.title} description={section.description} />
                  <div className="divide-y divide-line">
                    {section.items.map(item => (
                      <div key={item.key} className="py-3 first:pt-0 last:pb-0">
                        <Checkbox
                          checked={Boolean(values[item.key])}
                          disabled={saving === item.key}
                          onChange={e => toggle(item.key, e.target.checked)}
                          label={<span className="text-sm font-semibold text-ink">{item.label}</span>}
                        />
                        <p className="mt-1 pl-7 text-[13px] text-ink-muted">{item.hint}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
