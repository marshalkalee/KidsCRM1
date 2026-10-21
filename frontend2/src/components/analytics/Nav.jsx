import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Tabs } from '../../ui'
import { PageGroupContext } from '../../ui/pageGroup'
import { t } from '../../i18n'
import { REPORTS } from './meta'

/**
 * Раздел «Аналитика»: вкладки отчётов — внутри шапки страницы, как у
 * «Денег» (PageGroupContext). Период и филиалы переходят вместе с
 * адресом (?period=…).
 */
export function AnalyticsSection() {
  const { pathname, search } = useLocation()
  const navigate = useNavigate()
  const tabs = (
    <Tabs
      tabs={REPORTS}
      value={pathname.replace(/\/$/, '')}
      onChange={path => navigate(`${path}${search}`)}
    />
  )
  return (
    <PageGroupContext.Provider value={{ title: t('Аналитика'), tabs }}>
      <Outlet />
    </PageGroupContext.Provider>
  )
}
