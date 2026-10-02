import { useEffect, useState } from 'react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'

/*
 * Данные главной — из тех же API, что экраны (цифры совпадают с
 * «Задолженностями», «Продлениями», аналитикой). Запросы параллельно;
 * блок, на который у роли нет прав, не запрашивается, упавший — просто
 * не показывается (undefined), остальная главная работает.
 */

function isoDate(date) {
  const pad = n => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

const get = (url, params) => api.get(url, { params }).then(r => r.data)

export function useDashboardData() {
  const { can, user } = useSession()
  const [data, setData] = useState(null)

  useEffect(() => {
    let alive = true
    const today = new Date()
    const monthAgo = new Date(today)
    monthAgo.setDate(today.getDate() - 29)
    const money = can('can_view_client_money')
    const analytics = can('can_view_analytics')
    const childCount = status => get('clients/children/table/', { status, page_size: 1 }).then(r => r.count)

    const requests = {
      attention: get('notifications/').then(r => r.items),
      active: childCount('active'),
      paused: childCount('paused'),
      left: childCount('left'),
      groups: get('groups/', { status: 'active' }),
      lessons: get('schedule/', {
        date_from: isoDate(today),
        date_to: isoDate(today),
        ...(user?.role === 'teacher' ? { teacher: user.id } : {}),
      }),
      birthdays: get('clients/children/birthdays/', { days: 7 }),
      ...(money ? {
        debts: get('subscriptions/debtors/', { page_size: 1 }),
        renewals: get('subscriptions/renewals/', { page_size: 4 }),
      } : {}),
      // За 30 дней, а не «с 1-го числа»: в начале месяца главная не пустая.
      ...(analytics ? {
        revenue: get('analytics/metrics/', {
          metrics: 'revenue,payments_count,average_check',
          period: 'custom',
          from: isoDate(monthAgo),
          to: isoDate(today),
          compare: 0,
          series: 0,
        }).then(r => r.metrics),
      } : {}),
    }
    const keys = Object.keys(requests)
    Promise.allSettled(Object.values(requests)).then(results => {
      if (!alive) return
      setData(Object.fromEntries(keys.map((key, i) => [key, results[i].status === 'fulfilled' ? results[i].value : undefined])))
    })
    return () => { alive = false }
  }, [can, user])

  return data
}
