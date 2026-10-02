import axios from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'

/*
 * API кабинета родителя (backend: domains/people/portal, docs/parent-portal.md).
 *
 * Свой клиент, а не api/axios.js сотрудников: другой токен
 * («Authorization: Parent …»), другой адрес входа, и 401 здесь значит
 * «сессия кабинета истекла», а не «продлить JWT».
 *
 * Плохая связь: каждый удачный GET сохраняется в localStorage. Если сети
 * нет, usePortalData отдаёт сохранённое с пометкой stale и временем —
 * экран показывает «нет связи, данные от …» (TRU-137).
 */

const TOKEN_KEY = 'kc-parent-token'
const CACHE_PREFIX = 'kc-parent-cache:'
export const SESSION_EXPIRED_EVENT = 'kc-parent-session-expired'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* приватный режим — вход не запомнится */ }
}

/** Выход: токен и сохранённые данные — чужим глазам на общем телефоне не нужны. */
export function forgetParent() {
  setToken(null)
  try {
    Object.keys(localStorage).filter(k => k.startsWith(CACHE_PREFIX)).forEach(k => localStorage.removeItem(k))
  } catch { /* нечего чистить */ }
}

const portal = axios.create({ baseURL: '/api/v1/portal/', timeout: 15000 })

portal.interceptors.request.use(config => {
  const token = getToken()
  if (token && !config.anonymous) config.headers.Authorization = `Parent ${token}`
  return config
})

portal.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 401 && !error.config?.anonymous) {
      forgetParent()
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
    }
    throw error
  },
)

export default portal

/** Текст ошибки для родителя: сервер присылает {detail}, без сети — своё. */
export function portalError(error, fallback) {
  if (!error?.response) return fallback.offline
  return error.response.data?.detail || fallback.other
}

function readCache(url) {
  try {
    const raw = localStorage.getItem(CACHE_PREFIX + url)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writeCache(url, data) {
  try {
    localStorage.setItem(CACHE_PREFIX + url, JSON.stringify({ data, savedAt: new Date().toISOString() }))
  } catch { /* нет места — просто не сохраним */ }
}

/**
 * GET кабинета с сохранением на случай плохой связи — основа экранов
 * кабинета (контракт для экранов Дарьи, docs/parent-portal.md):
 *   const { data, loading, error, stale, savedAt, reload } = usePortalData(`children/${id}/schedule/`)
 * - сначала сразу отдаёт сохранённое (если есть), потом свежее с сервера;
 * - сети нет — остаётся сохранённое, stale=true, savedAt — когда получено;
 * - url=null — ничего не грузить (например, ребёнок ещё не выбран).
 */
export function usePortalData(url) {
  const [state, setState] = useState(() => initial(url))
  const alive = useRef(true)
  // Сменился адрес (другой ребёнок) — сразу показать его сохранённое, не прежнего.
  if (state.url !== url) setState(initial(url))

  const fetchData = useCallback(() => {
    if (!url) return
    portal.get(url)
      .then(({ data }) => {
        writeCache(url, data)
        if (alive.current) setState({ url, data, loading: false, error: null, stale: false, savedAt: null })
      })
      .catch(error => {
        if (!alive.current) return
        const cached = readCache(url)
        const offline = !error.response
        setState({
          url,
          data: cached?.data ?? null,
          loading: false,
          error: cached && offline ? null : error,
          stale: Boolean(cached && offline),
          savedAt: cached?.savedAt ?? null,
        })
      })
  }, [url])

  // Первая загрузка: loading уже true из initial().
  useEffect(() => {
    alive.current = true
    fetchData()
    return () => { alive.current = false }
  }, [fetchData])

  const reload = useCallback(() => {
    setState(s => ({ ...s, loading: true, error: null }))
    fetchData()
  }, [fetchData])

  const { url: _url, ...rest } = state
  return { ...rest, reload }
}

function initial(url) {
  const cached = url ? readCache(url) : null
  return { url, data: cached?.data ?? null, loading: Boolean(url), error: null, stale: false, savedAt: cached?.savedAt ?? null }
}
