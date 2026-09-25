import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1/',
})

api.interceptors.request.use(config => {
  const token = localStorage.getItem('access')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

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
