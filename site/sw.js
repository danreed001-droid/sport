// Pick Sheet service worker: makes the site installable as an app and lets it
// open without a connection. Network first, always: every page and data.json
// load fresh when online (picks and lines change all day); the saved copy is
// only a fallback when the network fails. Only this site's own files are cached.
const CACHE = 'picksheet-v1';
const SHELL = ['./', 'index.html', 'grading.html', 'manual.html', 'data.json', 'manifest.webmanifest',
               'icons/icon-192.png', 'icons/icon-512.png', 'icons/apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
      }
      return res;
    }).catch(() => caches.match(req, {ignoreSearch: true})
      .then(hit => hit || (req.mode === 'navigate' ? caches.match('index.html') : undefined))
      .then(hit => hit || new Response('Offline', {status: 503, statusText: 'Offline'})))
  );
});
