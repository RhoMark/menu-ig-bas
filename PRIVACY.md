# Politique de confidentialité — Menu IG Bas

**Dernière mise à jour : 27 avril 2026 (V2.10.0)**

Cette page décrit comment l'application **Menu IG Bas** gère tes données. Le principe directeur est simple : **rien ne quitte ton appareil**.

---

## 🔒 Ce qui est collecté

**Aucune donnée n'est collectée par un serveur, par nous, ou par un tiers.**

L'application Menu IG Bas est une **PWA (Progressive Web App)** qui s'exécute entièrement dans ton navigateur. Il n'y a pas de backend, pas de compte, pas de cloud, pas de système de tracking.

Concrètement :
- ❌ Aucun analytics (Google Analytics, Plausible, Matomo, etc.)
- ❌ Aucun pixel publicitaire (Facebook, Google Ads, etc.)
- ❌ Aucun cookie tiers
- ❌ Aucune connexion réseau pour fonctionner (à part la première installation)
- ❌ Aucun script externe sauf React et Tailwind via CDN (chargés une fois, mis en cache)

---

## 💾 Ce qui est stocké, et où

Tes données restent **uniquement sur ton appareil**, dans la mémoire de ton navigateur :

| Type de donnée | Où c'est stocké |
|---|---|
| Profil familial (membres, âges) | `localStorage` du navigateur |
| Allergies, intolérances, exclusions | `localStorage` du navigateur |
| Menus générés et historique | `localStorage` du navigateur |
| Notes de recettes | `localStorage` du navigateur |
| Préférences (équipement, budget, etc.) | `localStorage` du navigateur |

**Conséquences à connaître :**
- Si tu vides le cache de ton navigateur, **tes données sont perdues**.
- Si tu utilises plusieurs navigateurs ou appareils, **chacun a ses propres données** (pas de synchronisation automatique).
- Pour ne rien perdre : utilise le bouton **« Exporter »** dans Paramètres → Sauvegarde régulièrement.

**Depuis la V2.10.0**, le contenu du `localStorage` est **chiffré au repos** avec **AES-GCM 256 bits** et une clé maître non-extractable stockée dans IndexedDB. Le navigateur garantit que la clé ne peut jamais sortir de ton appareil, même via un script malveillant. Aucun changement côté usage : transparent pour toi, mais protection réelle si quelqu'un dump ton stockage.

⚠️ Conséquence importante : si tu effaces le stockage du site (ou si Safari iOS le purge automatiquement après plusieurs jours sans visite), **la clé est perdue avec**. Une option de récupération est proposée à l'écran : importer un export JSON récent ou tout réinitialiser. **Fais un export JSON régulièrement** depuis Paramètres → Sauvegarde — c'est ton filet de sécurité.

---

## 📜 Tes droits RGPD

Le RGPD européen te donne plusieurs droits sur tes données. Comme on ne collecte rien, ces droits s'appliquent à ce qui est stocké chez toi :

### ✅ Droit d'accès
**Toutes tes données sont visibles dans l'application** (Paramètres → Famille, Allergies, Préférences ; vue Historique pour les menus passés ; etc.). Tu peux aussi inspecter le `localStorage` directement via les DevTools de ton navigateur.

### ✅ Droit de rectification
Tu peux modifier **toutes les données** depuis l'interface (membres, allergies, notes de recettes, etc.).

### ✅ Droit à l'effacement
Le bouton **« Tout effacer et recommencer »** dans Paramètres → Zone dangereuse supprime l'intégralité de tes données.

Tu peux aussi vider le `localStorage` via les paramètres de ton navigateur.

### ✅ Droit à la portabilité
Le bouton **« Exporter »** dans Paramètres → Sauvegarde télécharge un fichier JSON contenant **toutes tes données dans un format lisible et standard**. Tu peux l'utiliser pour migrer vers une autre instance, faire un backup, ou inspecter le contenu.

---

## 🛡️ Sécurité

- Le code de l'application est **open source** et public sur GitHub : [RhoMark/menu-ig-bas](https://github.com/RhoMark/menu-ig-bas). Tu peux l'auditer, le forker, ou contribuer.
- Le code est servi via **GitHub Pages** sur HTTPS (certificat valide, signé par Let's Encrypt).
- **Depuis la V2.10.0**, les données stockées localement sont chiffrées AES-GCM 256 avec clé non-extractable en IndexedDB.
- Aucun cookie. Aucune donnée envoyée par le réseau pendant l'usage.

---

## 🍪 Cookies

L'application **n'utilise pas de cookies**. La persistance se fait via `localStorage` et `IndexedDB`, qui sont des mécanismes de stockage navigateur, distincts des cookies, et qui ne sont jamais transmis automatiquement à un serveur.

---

## 🌐 Transferts internationaux

**Aucun transfert.** Tes données ne quittent jamais ton appareil. Le code de l'application est hébergé sur GitHub Pages (États-Unis) mais il est **statique** : aucune information n'est envoyée du client vers GitHub pendant l'utilisation, sauf le téléchargement initial des fichiers HTML/JS/CSS (comme n'importe quel site web).

---

## 🧒 Mineurs

L'application peut être utilisée pour planifier des repas pour des enfants (membres mineurs du foyer). Les données les concernant (prénom, année de naissance, allergies) ne quittent pas l'appareil et ne font l'objet d'aucun traitement automatisé en dehors du calcul des quantités.

---

## 📞 Contact

Pour toute question sur cette politique :
- Ouvre une issue publique : [github.com/RhoMark/menu-ig-bas/issues](https://github.com/RhoMark/menu-ig-bas/issues)
- Le contact est l'email noreply GitHub associé au compte mainteneur (visible dans l'historique git).

---

## 🔄 Évolutions futures

Ce projet pourrait à terme proposer une option **opt-in** de synchronisation multi-appareil. Si cela arrive :
- Ce sera **explicitement opt-in** (jamais activé par défaut).
- Le chiffrement sera **end-to-end** : le serveur ne pourra jamais lire le contenu.
- Une mise à jour de cette politique sera publiée avec les détails.
- Le code restera open source et auditable.

Tant que cette option n'existe pas, **tes données restent strictement locales**.

---

*Cette politique est versionnée dans le code source. Tout changement passe par un commit public et est tracé dans l'historique git.*
