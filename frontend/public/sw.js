/* Kiwi Service Worker：只处理 Web Push，不做离线缓存。 */
self.addEventListener('install', () => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
})

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch (error) {
    data = {}
  }
  const title = data.title || 'Kiwi'
  const options = {
    body: data.body || '有新的学习提醒',
    tag: data.tag || 'kiwi-reminder',
    data: { url: data.url || '/' },
    icon: '/favicon.svg',
    badge: '/favicon.svg',
    renotify: false,
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(
    (event.notification.data && event.notification.data.url) || '/',
    self.location.origin,
  ).href
  event.waitUntil(
    (async () => {
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const client of clients) {
        if (client.url === target && 'focus' in client) return client.focus()
      }
      if (self.clients.openWindow) return self.clients.openWindow(target)
      return undefined
    })(),
  )
})
