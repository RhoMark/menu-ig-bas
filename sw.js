// Service Worker — Menu IG Bas
// -----------------------------
// Permet à l'app de fonctionner hors-ligne (et de se charger très vite en
// ligne) en mettant en cache index.html, le manifest, les icônes, et les
// dépendances CDN (Tailwind, React, Babel).
//
// Stratégies :
// - Navigation (HTML) → network-first : on essaie le réseau pour récupérer
//   une version à jour de l'app ; fallback cache si offline.
// - Assets statiques (icônes, manifest, JSON) → cache-first : on sert depuis
//   le cache si présent (rapide), sinon on télécharge et on cache.
// - CDN externes → cache-first avec opaque responses (mode no-cors).
//
// Versioning du cache : bumper CACHE_VERSION à chaque release qui modifie
// les ressources critiques. Les anciens caches sont purgés à l'activation.

const CACHE_VERSION = "menu-ig-bas-v2.24.0";

const CRITICAL_ASSETS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./apple-touch-icon.png",
  "./icon-192.png",
  "./icon-512.png",
];

const CDN_ASSETS = [
  "https://cdn.tailwindcss.com",
  "https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js",
  "https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.5/babel.min.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    // Critique : doit réussir, sinon le SW ne s'installe pas.
    await cache.addAll(CRITICAL_ASSETS);
    // CDN : best effort, on log les échecs sans bloquer l'install
    // (request "no-cors" → opaque response, mais le browser peut quand même la
    // restituer aux <script src="..."> tant que c'est servi depuis le cache).
    await Promise.allSettled(CDN_ASSETS.map(async (url) => {
      try {
        const resp = await fetch(url, {mode: "no-cors"});
        await cache.put(url, resp);
      } catch (e) {
        console.warn("[sw] CDN cache miss:", url, e);
      }
    }));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE_VERSION).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  // Navigation HTML → network-first (récupère les mises à jour, fallback offline).
  const isNavigation = req.mode === "navigate" ||
                       (req.destination === "document") ||
                       url.pathname.endsWith("/") ||
                       url.pathname.endsWith("index.html");
  if (isNavigation) {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_VERSION);
        cache.put(req, fresh.clone()).catch(() => {});
        return fresh;
      } catch (e) {
        const cached = await caches.match(req) || await caches.match("./index.html") || await caches.match("./");
        return cached || new Response("Hors-ligne et page non disponible en cache.", {status: 503});
      }
    })());
    return;
  }

  // Reste (assets, CDN) → cache-first.
  event.respondWith((async () => {
    const cached = await caches.match(req);
    if (cached) return cached;
    try {
      const isCrossOrigin = url.origin !== self.location.origin;
      const fresh = await fetch(req, isCrossOrigin ? {mode: "no-cors"} : undefined);
      // On cache si statut OK ou opaque (cross-origin no-cors).
      if (fresh && (fresh.ok || fresh.type === "opaque")) {
        const cache = await caches.open(CACHE_VERSION);
        cache.put(req, fresh.clone()).catch(() => {});
      }
      return fresh;
    } catch (e) {
      return new Response("", {status: 503, statusText: "Offline"});
    }
  })());
});
