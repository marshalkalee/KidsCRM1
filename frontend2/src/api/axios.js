import axios from 'axios'

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
    refreshing = (refresh ? axios.post(REFRESH_URL, { refresh }, { skipAuthRefresh: true }) : Promise.reject(new Error('нет refresh-токена')))
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

// access живёт 30 минут (SIMPLE_JWT.ACCESS_TOKEN_LIFETIME) — без этого любой
// запрос после истечения падал с "Given token not valid for any token type"
// прямо посреди работы (например, в "Кого обзвонить"), и единственным
// выходом был ручной перелогин. Теперь на первый 401 тихо обновляем access
// через refresh-токен и повторяем исходный запрос; если refresh тоже не
// прошёл (истёк за 7 дней или отозван) — на логин. Запросы, случившиеся
// пока идёт обновление, ждут его результата вместо того, чтобы каждый
// запускал свой собственный refresh.
let refreshPromise = null

function refreshAccessToken() {
  if (!refreshPromise) {
    const refresh = localStorage.getItem('refresh')
    refreshPromise = axios
      .post('/api/v1/users/auth/refresh/', { refresh })
      .then(res => {
        localStorage.setItem('access', res.data.access)
        if (res.data.refresh) localStorage.setItem('refresh', res.data.refresh)
        return res.data.access
      })
      .finally(() => { refreshPromise = null })
  }
  return refreshPromise
}

api.interceptors.response.use(
  res => res,
  async error => {
    const { config, response } = error
    const isAuthRoute = config?.url?.includes('auth/login') || config?.url?.includes('auth/refresh')
    if (response?.status === 401 && !config._retried && !isAuthRoute && localStorage.getItem('refresh')) {
      config._retried = true
      try {
        const access = await refreshAccessToken()
        config.headers.Authorization = `Bearer ${access}`
        return api(config)
      } catch {
        localStorage.removeItem('access')
        localStorage.removeItem('refresh')
        window.location.href = '/login'
        return Promise.reject(error)
      }
    }
    return Promise.reject(error)
  }
)

export default api
