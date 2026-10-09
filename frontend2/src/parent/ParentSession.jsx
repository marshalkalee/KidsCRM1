import { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { lang, setLang } from '../i18n'
import portal, { SESSION_EXPIRED_EVENT, forgetParent, getToken, setToken, usePortalData } from './api'
import { disablePush } from './push'
import { ParentContext, useParent } from './useParent'

/*
 * Сессия кабинета родителя: профиль, дети, выбранный ребёнок.
 * Один ребёнок — он выбран сразу; несколько — последний выбранный
 * запоминается на этом телефоне (TRU-136, TRU-138).
 */

const CHILD_KEY = 'kc-parent-child'
const PORTAL_LANGUAGES = ['ru', 'kk']

function readChild() {
  try { return localStorage.getItem(CHILD_KEY) } catch { return null }
}

export function ParentSessionProvider({ children }) {
  const navigate = useNavigate()
  const [token, setTokenState] = useState(getToken)
  const me = usePortalData(token ? 'me/' : null)
  const [childId, setChildIdState] = useState(readChild)

  // Сервер сказал 401 — сессия истекла или её отозвали на другом устройстве.
  useEffect(() => {
    const expired = () => {
      setTokenState(null)
      navigate('/parent/login', { replace: true, state: { expired: true } })
    }
    window.addEventListener(SESSION_EXPIRED_EVENT, expired)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired)
  }, [navigate])

  // Язык кабинета — из профиля родителя (ru/kk), он выбирает его сам.
  useEffect(() => {
    const preferred = me.data?.language
    if (PORTAL_LANGUAGES.includes(preferred) && preferred !== lang) setLang(preferred)
  }, [me.data?.language])

  const kids = useMemo(() => me.data?.children || [], [me.data])
  const child = kids.find(c => c.id === childId) || kids[0] || null

  const selectChild = useCallback(id => {
    try { localStorage.setItem(CHILD_KEY, id) } catch { /* не запомнится */ }
    setChildIdState(id)
  }, [])

  const signIn = useCallback(newToken => {
    setToken(newToken)
    setTokenState(newToken)
  }, [])

  const signOut = useCallback(async ({ everywhere = false } = {}) => {
    // Общий телефон: напоминания прошлого родителя этому устройству не нужны.
    await disablePush().catch(() => {})
    await portal.post('auth/logout/', { everywhere }).catch(() => {})
    forgetParent()
    setTokenState(null)
    navigate('/parent/login', { replace: true })
  }, [navigate])

  const value = useMemo(() => ({
    signedIn: Boolean(token),
    me,
    profile: me.data,
    children: kids,
    child,
    selectChild,
    signIn,
    signOut,
  }), [token, me, kids, child, selectChild, signIn, signOut])

  return <ParentContext.Provider value={value}>{children}</ParentContext.Provider>
}

export function RequireParent({ children }) {
  const { signedIn } = useParent()
  const location = useLocation()
  if (!signedIn) return <Navigate to="/parent/login" replace state={{ from: location.pathname }} />
  return children
}
