# Serveur de synchro maison « La Mijoterie »

Petit serveur **aveugle** qui permet aux appareils d'une famille de partager
leur foyer Menu IG Bas sur le réseau de la maison, sans aucun cloud.

- **Ne lit rien** : il reçoit un foyer déjà chiffré sur l'appareil (AES-GCM 256,
  clé de foyer partagée par QR code, jamais envoyée au serveur). Il ne stocke
  qu'un identifiant aléatoire, l'enveloppe chiffrée, les clés publiques des
  appareils et leur nom chiffré.
- **Zéro dépendance** : Node ≥ 22 (`node:http`, `node:sqlite`, `node:crypto`).
- **Jamais exposé directement** : écoute `127.0.0.1` ; un reverse proxy HTTPS
  (Caddy) lui transmet `/api/*`.
- **Règles** : 8 appareils max par foyer, tout nouvel appareil attend
  l'approbation d'un appareil administrateur, requêtes signées par appareil
  (ECDSA P-256, anti-rejeu), dernière version + 2 conservées, purge à 30 jours.

```bash
node --disable-warning=ExperimentalWarning sync-server/server.mjs
# variables : MIJOTERIE_SYNC_PORT (8787), MIJOTERIE_SYNC_DB (~/.local/share/mijoterie/sync.db)
node --disable-warning=ExperimentalWarning scripts/test-sync-server.mjs   # tests
```

Dans l'app, la fonction est en test (mode labo `?sync=lab`), désactivée par défaut.
