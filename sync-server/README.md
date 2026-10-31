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

## Ne jamais dépendre d'un seul appareil administrateur

Les clés d'un appareil vivent dans le stockage de son navigateur. Si ce
stockage est effacé (nettoyage, réinitialisation, option « supprimer les
cookies et données des sites à la fermeture »), l'appareil perd sa place.
S'il était le **seul** administrateur, plus personne ne peut approuver.

- Dans l'app : « 📱 Appareils » → **Rendre admin** sur un 2ᵉ appareil d'adulte
  (l'app le rappelle tant qu'il n'y a qu'un admin).
- Firefox avec effacement à la fermeture : ajouter une exception
  **Autoriser** pour l'adresse de l'app (Paramètres → Vie privée et sécurité →
  Cookies et données de sites → Gérer les exceptions).
- **Secours** si le seul admin est perdu : un appareil restant affiche le code
  du foyer, le nouvel appareil demande à rejoindre, puis sur le serveur (après
  une copie de la base) on passe ce nouvel appareil `approved = 1, is_admin = 1`
  et on supprime l'ancien appareil de la table `devices`. Aucune donnée en
  clair n'est touchée (tout reste chiffré).
