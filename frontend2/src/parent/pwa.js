/*
 * Установка кабинета на телефон (TRU-137): манифест, иконки и сервис-воркер
 * только для /parent — у CRM сотрудников этого нет. Ссылки на манифест
 * ставятся при открытии кабинета: Chrome и Safari читают их из DOM.
 * Push-уведомления — V3 (ТЗ п. 6): сервис-воркер их не обрабатывает, но
 * подписку можно добавить в тот же public/parent/sw.js.
 */

function addHead(tag, attrs) {
  const selector = Object.entries(attrs).slice(0, 2).map(([k, v]) => `[${k}="${v}"]`).join('')
  if (document.head.querySelector(`${tag}${selector}`)) return
  const el = document.createElement(tag)
  Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v))
  document.head.appendChild(el)
}

export function installPwa() {
  addHead('link', { rel: 'manifest', href: '/parent/manifest.json' })
  addHead('link', { rel: 'apple-touch-icon', href: '/parent/icon-180.png' })
  addHead('meta', { name: 'theme-color', content: '#e4586e' })
  addHead('meta', { name: 'apple-mobile-web-app-capable', content: 'yes' })
  addHead('meta', { name: 'mobile-web-app-capable', content: 'yes' })
  addHead('meta', { name: 'apple-mobile-web-app-title', content: 'KidsCRM' })
  addHead('meta', { name: 'apple-mobile-web-app-status-bar-style', content: 'default' })
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/parent/sw.js', { scope: '/parent/' }).catch(() => {
      // Без сервис-воркера кабинет работает, просто не откроется без сети.
    })
  }
}
