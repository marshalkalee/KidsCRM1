import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import api, { ACTIVE_BRANCH_KEY, clearTokens } from '../api/axios'
import { Spinner } from '../ui'

/**
 * Кто вошёл и что ему можно (TRU-80): пользователь и permissions из
 * /users/auth/me/ — те же флаги, что у старого веба (role_permissions.py:
 * can_manage_branches, can_view_client_money …). Скрытие по ним в меню и
 * кнопках — удобство; настоящая проверка — на API.
 *
 * Плюс активный филиал: хранится в браузере и уходит в API заголовком
 * X-Branch-Id (api/axios.js). null — «все филиалы».
 */
const SessionContext = createContext(null)

export const ROLE_LABELS = {
  owner: 'Владелец',
  manager: 'Управляющий',
  admin: 'Администратор',
  teacher: 'Преподаватель',
  accountant: 'Бухгалтер',
}

function readStoredBranch() {
  try { return localStorage.getItem(ACTIVE_BRANCH_KEY) } catch { return null }
}

export function SessionProvider({ children }) {
  const [user, setUser] = useState(null)
  const [branches, setBranches] = useState([])
  const [activeBranchId, setActiveBranchIdState] = useState(readStoredBranch)
  const [status, setStatus] = useState(localStorage.getItem('access') ? 'loading' : 'anonymous')

  const load = useCallback(async () => {
    if (!localStorage.getItem('access')) {
      setStatus('anonymous')
      return
    }
    setStatus('loading')
    try {
      const [me, branchList] = await Promise.all([
        api.get('users/auth/me/'),
        api.get('branches/').catch(() => ({ data: [] })),
      ])
      setUser(me.data)
      const active = (branchList.data.results || branchList.data).filter(b => b.is_active !== false)
      setBranches(active)
      // Сохранённый филиал мог быть архивирован — тогда «все филиалы».
      setActiveBranchIdState(current => (active.some(b => String(b.id) === String(current)) ? current : null))
      setStatus('ready')
    } catch {
      // 401 с протухшим refresh уже увёл на /login (api/axios.js).
      setStatus('anonymous')
    }
  }, [])

  useEffect(() => { load() }, [load])

  const setActiveBranchId = useCallback(id => {
    try {
      if (id) localStorage.setItem(ACTIVE_BRANCH_KEY, id)
      else localStorage.removeItem(ACTIVE_BRANCH_KEY)
    } catch { /* приватный режим — филиал просто не запомнится */ }
    setActiveBranchIdState(id || null)
  }, [])

  const logout = useCallback(async () => {
    const refresh = localStorage.getItem('refresh')
    // Refresh — в blacklist на сервере, чтобы украденный токен не жил 7 дней.
    if (refresh) await api.post('users/auth/logout/', { refresh }).catch(() => {})
    clearTokens()
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo(() => ({
    user,
    status,
    permissions: user?.permissions || {},
    can: key => Boolean(user?.permissions?.[key]),
    roleLabel: ROLE_LABELS[user?.role] || user?.role,
    branches,
    activeBranchId,
    activeBranch: branches.find(b => String(b.id) === String(activeBranchId)) || null,
    setActiveBranchId,
    reload: load,
    logout,
  }), [user, status, branches, activeBranchId, setActiveBranchId, load, logout])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession() {
  return useContext(SessionContext)
}

/** Страницы только для вошедших: нет токена — на /login с возвратом обратно. */
export function RequireAuth({ children }) {
  const { status } = useSession()
  const location = useLocation()
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  if (status === 'loading') return <Spinner className="min-h-screen" />
  return children
}

/** Экран только для роли с правом `permission` (иначе — «нет доступа»). */
export function RequirePermission({ permission, children }) {
  const { can } = useSession()
  if (!can(permission)) {
    return (
      <div className="py-20 text-center">
        <p className="font-semibold text-ink">Нет доступа</p>
        <p className="mt-1 text-sm text-ink-muted">Этот раздел недоступен для вашей роли.</p>
      </div>
    )
  }
  return children
}
