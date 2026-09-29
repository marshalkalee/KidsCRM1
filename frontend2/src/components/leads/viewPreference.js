const STORAGE_KEY = 'kidscrm:leads-view'

export function getLeadsViewPreference() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'table' ? 'table' : 'board'
  } catch {
    return 'board'
  }
}

export function setLeadsViewPreference(view) {
  try {
    window.localStorage.setItem(STORAGE_KEY, view === 'table' ? 'table' : 'board')
  } catch {
    // В приватном режиме хранилище может быть недоступно; URL всё равно
    // сохраняет выбранный вид на время текущей навигации.
  }
}
