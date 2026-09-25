import axios from 'axios'
import { t } from '../i18n'

// Авторизация для всех запросов к API (TRU-79): токен из localStorage и
// автоматическое продление access-токена при 401.
//
// Перехватчики ставятся и на общий клиент `api`, и на стандартный `axios`:
// часть страниц зовёт `axios.get('/api/v1/...')` напрямую со своим
// заголовком Authorization — они тоже должны продлевать токен, а не
// выкидывать пользователя через 30 минут (срок жизни access в SIMPLE_JWT).

const REFRESH_URL = '/api/v1/users/auth/refresh/'
// На эти адреса 401 — это «неверный пароль»/«протухший refresh», а не повод продлевать.
const NO_REFRESH = ['/users/auth/login/', '/users/auth/refresh/', '/users/auth/register/']

// Активный филиал из переключателя в шапке (session/SessionContext.jsx) —
// уходит в API заголовком X-Branch-Id (backend: core/active_branch.py).
export const ACTIVE_BRANCH_KEY = 'activeBranchId'

let refreshing = null // один запрос продления на все одновременно упавшие запросы

function isApiUrl(config) {
  const url = config.url || ''
  return url.startsWith('/api/') || (config.baseURL || '').startsWith('/api/')
}

export function clearTokens() {
  localStorage.removeItem('access')
  localStorage.removeItem('refresh')
}

function logout() {
  clearTokens()
  if (window.location.pathname !== '/login') window.location.assign('/login')
}

function refreshAccessToken() {
  if (!refreshing) {
    const refresh = localStorage.getItem('refresh')
    refreshing = (refresh ? axios.post(REFRESH_URL, { refresh }, { skipAuthRefresh: true }) : Promise.reject(new Error(t('нет refresh-токена'))))
      .then(res => {
        localStorage.setItem('access', res.data.access)
        // Ротация включена — вместе с access приходит новый refresh, старый уже в blacklist.
        if (res.data.refresh) localStorage.setItem('refresh', res.data.refresh)
        return res.data.access
      })
      .finally(() => { refreshing = null })
  }
  return refreshing
}

export function installAuth(instance) {
  instance.interceptors.request.use(config => {
    if (!isApiUrl(config) || config.skipAuthRefresh) return config
    const token = localStorage.getItem('access')
    // Всегда текущий токен — даже если страница подставила свой заголовок раньше.
    if (token) config.headers.Authorization = `Bearer ${token}`
    const branch = localStorage.getItem(ACTIVE_BRANCH_KEY)
    if (branch) config.headers['X-Branch-Id'] = branch
    return config
  })

  instance.interceptors.response.use(
    response => response,
    async error => {
      const config = error.config
      const url = config?.url || ''
      const skip = !config || config.skipAuthRefresh || config._retried || NO_REFRESH.some(u => url.includes(u))
      if (error.response?.status !== 401 || skip || !isApiUrl(config)) throw error

      try {
        const access = await refreshAccessToken()
        config._retried = true
        config.headers.Authorization = `Bearer ${access}`
        return instance(config)
      } catch {
        logout()
        throw error
      }
    },
  )
  return instance
}

const api = axios.create({ baseURL: '/api/v1/' })
installAuth(api)
installAuth(axios)

export default api
