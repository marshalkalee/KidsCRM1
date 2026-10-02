import { useLocation, useNavigate } from 'react-router-dom'
import { Tabs } from '../../ui'
import { REPORTS } from './meta'

/** Вкладки отчётов. Период и филиалы переходят вместе с адресом (?period=…). */
export function AnalyticsNav() {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  return (
    <Tabs
      className="mb-4"
      tabs={REPORTS}
      value={pathname.replace(/\/$/, '')}
      onChange={path => navigate(`${path}${search}`)}
    />
  )
}
