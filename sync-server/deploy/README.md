# Déploiement du serveur de synchro sur un VPS (Phase 2·C)

Serveur **aveugle** : il ne stocke que des foyers chiffrés par les appareils et les clés
publiques des appareils. Aucune IP n'est journalisée (pas de `log` dans le bloc Caddy, limites
de requêtes en mémoire sous forme d'empreinte salée).

Cible testée : Debian 12 arm64 + Caddy. `SYNC_DOMAIN` = le sous-domaine de l'API
(ex. `sync.exemple.eu`), avec un enregistrement DNS A/AAAA vers le VPS.

## 1. Node 22 (binaire officiel, vérifié par somme SHA-256)

```bash
NODE=v22.x.y   # dernière 22 LTS sur https://nodejs.org/dist/latest-v22.x/
cd /tmp && curl -fsSLO https://nodejs.org/dist/$NODE/node-$NODE-linux-arm64.tar.xz \
  && curl -fsSLO https://nodejs.org/dist/$NODE/SHASUMS256.txt \
  && grep " node-$NODE-linux-arm64.tar.xz\$" SHASUMS256.txt | sha256sum -c - \
  && sudo tar -xJf node-$NODE-linux-arm64.tar.xz -C /opt \
  && sudo ln -sf /opt/node-$NODE-linux-arm64/bin/node /usr/local/bin/node && node -v
```

## 2. Utilisateur dédié + fichiers (depuis le dossier `sync-server/` copié sur le VPS)

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mijoterie-sync
sudo install -d -m 0755 /opt/mijoterie-sync
sudo install -m 0644 server.mjs deploy/backup.mjs /opt/mijoterie-sync/
sudo install -m 0644 deploy/mijoterie-sync.service deploy/mijoterie-sync-backup.service \
  deploy/mijoterie-sync-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mijoterie-sync mijoterie-sync-backup.timer
curl -s http://127.0.0.1:8787/api/v1/health    # {"ok":true}
```

## 3. Caddy : ajouter ce bloc à /etc/caddy/Caddyfile

```caddy
SYNC_DOMAIN {
	# Pas de directive « log » : aucun journal d'accès, donc aucune IP conservée.
	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
		-Server
	}
	request_body {
		max_size 3MB
	}
	reverse_proxy /api/* 127.0.0.1:8787
	respond 404
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
curl -s https://SYNC_DOMAIN/api/v1/health
```

## 4. Mise à jour du serveur

```bash
sudo install -m 0644 server.mjs /opt/mijoterie-sync/ && sudo systemctl restart mijoterie-sync
```

## Réglages (variables d'environnement, dans le .service)

| Variable | Défaut | Rôle |
|---|---|---|
| `MIJOTERIE_SYNC_ORIGINS` | (vide = même origine seulement) | Adresses de l'app autorisées (CORS) |
| `MIJOTERIE_SYNC_TRUST_PROXY` | `0` | `1` derrière Caddy : IP du client lue dans `X-Forwarded-For` |
| `MIJOTERIE_SYNC_PER_MINUTE` | 300 | Requêtes / minute / IP |
| `MIJOTERIE_SYNC_CREATE_PER_HOUR` | 20 | Créations de foyer + demandes de jonction / heure / IP |
| `MIJOTERIE_SYNC_MAX_HOUSEHOLDS` | 5000 | Foyers au total |
| `MIJOTERIE_SYNC_MAX_BYTES` | 2 Go | Taille totale des foyers chiffrés |
