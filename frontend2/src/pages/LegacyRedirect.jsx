import { Navigate, useLocation } from 'react-router-dom'
import NotFound from './NotFound'

// Адреса старого серверного веба (удалён в TRU-88) → экраны frontend2:
// закладки и ссылки из чатов продолжают открываться.
const RULES = [
  [/^\/clients\/children\/create\/?$/, () => '/children'],
  [/^\/clients\/children\/([0-9a-f-]{36})(\/edit)?\/?$/, m => `/children/${m[1]}`],
  [/^\/clients\/children\/?$/, () => '/children'],
  [/^\/clients\/import\/?.*$/, () => '/children/import'],
  [/^\/clients\/parents\/create\/?$/, () => '/parents'],
  [/^\/clients\/parents\/([0-9a-f-]{36})(\/edit)?\/?$/, m => `/parents/${m[1]}`],
  [/^\/clients\/parents\/?$/, () => '/parents'],
  [/^\/settings\/branches\/([0-9a-f-]{36})\/rooms\/?$/, m => `/branches/${m[1]}/rooms`],
  [/^\/settings\/branches\/?.*$/, () => '/settings/structure?tab=branches'],
  [/^\/settings\/directions\/?.*$/, () => '/settings/structure?tab=directions'],
  [/^\/groups\/([0-9a-f-]{36})\/(edit|close)\/?$/, m => `/groups/${m[1]}`],
  [/^\/groups\/create\/?$/, () => '/groups'],
  [/^\/onboarding\/.+$/, () => '/onboarding'],
  [/^\/debtors\/?.*$/, () => '/money?tab=debts'],
  [/^\/payments\/child\/([0-9a-f-]{36})\/.*$/, m => `/children/${m[1]}?tab=payments`],
]

function legacyTarget(pathname) {
  for (const [pattern, to] of RULES) {
    const match = pathname.match(pattern)
    if (match) return to(match)
  }
  return null
}

/** Старый адрес — на новый экран, иначе «страница не найдена». */
export default function LegacyRedirect() {
  const { pathname } = useLocation()
  const target = legacyTarget(pathname)
  return target ? <Navigate to={target} replace /> : <NotFound />
}
