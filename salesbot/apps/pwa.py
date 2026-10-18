"""Instant apps: web app manifest and service worker so each business app installs from the browser."""

from __future__ import annotations

from typing import Any

from . import AppSpec


def manifest(spec: AppSpec) -> dict[str, Any]:
    base = f"/app/{spec.slug}"
    return {
        "id": base,
        "name": spec.name,
        "short_name": spec.short_name,
        "description": spec.description or f"{spec.name} on MyOps: your AI team.",
        "start_url": f"{base}?source=homescreen",
        "scope": "/",
        "display": "standalone",
        "background_color": spec.background,
        "theme_color": spec.color,
        "icons": [
            {"src": f"{base}/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": f"{base}/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": f"{base}/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }


def head_tags(spec: AppSpec) -> str:
    """Tags added to the web app's <head> when it is opened as this app."""
    base = f"/app/{spec.slug}"
    name = spec.name.replace('"', "&quot;").replace("<", "&lt;")
    return (
        f'<link rel="manifest" href="{base}/manifest.webmanifest">'
        f'<meta name="theme-color" content="{spec.color}">'
        f'<link rel="apple-touch-icon" href="{base}/icon-180.png">'
        f'<meta name="apple-mobile-web-app-capable" content="yes">'
        f'<meta name="mobile-web-app-capable" content="yes">'
        f'<meta name="apple-mobile-web-app-title" content="{name}">'
        f"<title>{name}</title>"
        "<script>if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});</script>"
    )


# Network first, so every update on the server shows up at once; the cached shell only covers
# going offline. API calls are never cached.
SERVICE_WORKER = """const CACHE = 'myops-shell-v1';
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return;
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && (e.request.mode === 'navigate' || url.pathname.match(/\\.(png|webmanifest)$/))) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
    }
    return res;
  }).catch(() => caches.match(e.request).then((r) => r || new Response('Offline: reconnect to reach your MyOps team.', { status: 503 }))));
});
"""
