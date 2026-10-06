import { useSearchParams } from 'react-router-dom'
import { Navigate } from 'react-router-dom'
import { useSession } from '../../session/SessionContext'
import { Tabs } from '../../ui'
import { PageGroupContext } from '../../ui/pageGroup'

/**
 * Раздел из вкладок: ?tab=<key> в адресе (ссылкой можно поделиться).
 * Вкладки без права не показываются; нет ни одной — на главную.
 * tabs: [{ key, label, permission?, element }]
 */
export default function PageGroup({ title, tabs }) {
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const allowed = tabs.filter(tab => !tab.permission || can(tab.permission))
  if (!allowed.length) return <Navigate to="/" replace />
  const active = allowed.find(tab => tab.key === params.get('tab')) || allowed[0]
  // Сменили вкладку — фильтры прошлой вкладки ей не нужны.
  const select = key => setParams({ tab: key })
  const strip = allowed.length > 1
    ? <Tabs tabs={allowed.map(({ key, label }) => ({ key, label }))} value={active.key} onChange={select} />
    : null
  return (
    <PageGroupContext.Provider value={{ title, tabs: strip }}>
      <div key={active.key}>{active.element}</div>
    </PageGroupContext.Provider>
  )
}

/** Старый адрес → вкладка раздела, с его параметрами (фильтры, ?overdue=1). */
export function TabRedirect({ to, tab }) {
  const [params] = useSearchParams()
  const next = new URLSearchParams(params)
  next.set('tab', tab)
  return <Navigate to={`${to}?${next}`} replace />
}
