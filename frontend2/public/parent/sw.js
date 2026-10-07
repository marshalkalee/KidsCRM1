/*
 * Сервис-воркер кабинета родителя (TRU-137). Задача одна: кабинет
 * открывается и без сети — с последними данными, которые экран сохранил
 * сам (src/parent/api.js). Поэтому кэшируется только оболочка приложения:
 * - страницы /parent… — сначала сеть, без сети — сохранённый index.html;
 * - /assets/… (имена с хешем, не меняются) — из кэша, если уже есть.
 * API не кэшируется здесь: данные детей — только в памяти экрана и
 * localStorage, который чистится при выходе.
 * Push (TRU-172): показать уведомление от центра рассылок и по нажатию
 * открыть нужный раздел кабинета (уже открытую вкладку — переключить).
 */
const SHELL = 'kc-parent-shell-v1'

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.add('/parent')).catch(() => {}))
  self.skipWaiting()
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith('kc-parent-shell-') && k !== SHELL).map(k => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', event => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then(response => {
          const copy = response.clone()
          caches.open(SHELL).then(cache => cache.put('/parent', copy))
          return response
        })
        .catch(() => caches.match('/parent')),
    )
    return
  }

  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/parent/icon')) {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request).then(response => {
        const copy = response.clone()
        caches.open(SHELL).then(cache => cache.put(request, copy))
        return response
      })),
    )
  }
})

self.addEventListener('push', event => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = { body: event.data && event.data.text() } }
  event.waitUntil(
    self.registration.showNotification(data.title || 'KidsCRM', {
      body: data.body || '',
      icon: '/parent/icon-192.png',
      badge: '/parent/icon-192.png',
      // Новое «абонемент заканчивается» заменяет старое, а не копится стопкой.
      tag: data.tag || undefined,
      data: { url: data.url || '/parent' },
    }),
  )
})

self.addEventListener('notificationclick', event => {
  event.notification.close()
  const url = new URL(event.notification.data?.url || '/parent', self.location.origin).href
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windows => {
      const open = windows.find(w => w.url.startsWith(self.location.origin + '/parent'))
      if (open) return open.navigate(url).then(w => (w || open).focus())
      return self.clients.openWindow(url)
    }),
  )
})
