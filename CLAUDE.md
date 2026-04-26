# Application Menu IG Bas pour la Santé

## Vision

PWA puis app multi-plateforme qui génère des menus hebdomadaires à
**Index Glycémique bas** pour les familles, avec recettes détaillées,
liste de courses et suivi dans le temps.

## Source de vérité fonctionnelle

📄 `Specifications_Menu_IG_Bas_V1.docx` — spec V1 complète (avril
2026). **Toujours s'y référer** avant d'implémenter une fonctionnalité,
proposer un changement de périmètre, ou répondre à une question sur
le « quoi ».

Ce CLAUDE.md ne contient que les invariants à connaître à chaque
session — pas le détail du périmètre.

## Règles non négociables

### Sécurité — allergies & intolérances
- Paramétrables **par membre** de la famille.
- **Aucune** recette contenant l'allergène ou ses traces potentielles
  ne doit être proposée — vérification renforcée jusqu'aux ingrédients
  composés (sauces, mélanges d'épices, préparations).
- Affichage d'alerte visuel (pictogramme + couleur rouge).
- Confirmation explicite à la saisie pour éviter la confusion avec
  une simple préférence de goût.

### Données personnelles (santé — sensibles)
- **Chiffrement au repos** obligatoire.
- Conformité **RGPD** : accès, rectification, effacement, portabilité.
- Consentement explicite pour tout usage secondaire.
- Aucune donnée santé ne transite sans nécessité fonctionnelle claire.

### Modèle d'hébergement & données
- **Code** : public sur GitHub (`RhoMark/menu-ig-bas`), servi via
  GitHub Pages pour permettre l'installation PWA sur iPhone, iPad, Mac
  et Android depuis une URL fixe.
- **Données utilisateur** : stockées **uniquement en local sur chaque
  appareil** (localStorage / IndexedDB). Aucune donnée famille,
  santé, allergies, menus, notes ou prix ne quitte le device.
- **Conséquence** : ne jamais proposer de backend qui collecte les
  données utilisateur, d'analytics, de tracker, ni de sync cloud
  activée par défaut. Toute fonctionnalité de partage ou de sync
  futur doit être explicitement opt-in et chiffrée de bout en bout.
- **Conséquence pour le repo public** : aucun secret, clé d'API,
  identifiant ou donnée perso ne doit jamais être commité — y compris
  dans `index.html`, les commits historiques, les issues, ou les
  templates GitHub.

### Style des recettes
Rédigées **comme si c'était un adolescent qui cuisine** :
- Pas d'implicite.
- Définir systématiquement les gestes techniques (« émincer »,
  « déglacer », « blanchir »…).
- Donner des repères visuels concrets (« jusqu'à ce que l'oignon
  devienne translucide »).

## Recommandations nutritionnelles internationales

Les menus générés doivent respecter les **recommandations
nutritionnelles reconnues** (OMS, EFSA, ANSES/PNNS pour la France,
WCRF). Un menu à IG bas peut être déséquilibré par ailleurs — ces
règles servent de garde-fous complémentaires.

Repères indicatifs à appliquer dans la génération (paramétrables et
modulables selon l'âge, le sexe et les pathologies de chaque membre) :

- **Œufs** : ≤ 10 par personne / semaine — compter aussi les œufs
  « cachés » dans les préparations (pâtisseries, sauces, pâtes
  fraîches…).
- **Viande rouge** : ≤ 500 g cuit / personne / semaine (WCRF/AICR).
- **Charcuteries / viandes transformées** : à limiter fortement
  (classées cancérogène certain par le CIRC/OMS).
- **Poisson** : 2 portions / semaine, dont 1 poisson gras
  (oméga-3 : sardine, maquereau, saumon…).
- **Fruits et légumes** : ≥ 5 portions / jour (≥ 400 g).
- **Légumineuses** : au moins 2 fois par semaine.
- **Céréales complètes** privilégiées sur les raffinées (cohérent
  avec l'objectif IG bas).
- **Sel** : ≤ 5 g / jour / adulte (OMS).
- **Sucres ajoutés** : < 10 % de l'apport énergétique, idéalement
  < 5 % (OMS).
- **Acides gras saturés** : < 10 % de l'apport énergétique.
- **Acides gras trans industriels** : < 1 % de l'apport énergétique.
- **Produits laitiers** : 2 à 3 portions / jour (selon âge).
- **Hydratation** : ≈ 1,5 L d'eau / jour / adulte.

Ces seuils sont des valeurs de départ. Avant production, les valeurs
définitives doivent être validées avec les sources officielles à jour
de la zone géographique de la famille.

## État technique actuel (V2.6.0)

PWA mono-fichier, démarrage léger pour itérer rapidement sur l'UX et
les données. À faire évoluer selon les besoins.

- `index.html` : tout le code (HTML + 7 tables JSON embarquées +
  React 18 + JSX transpilé par Babel en navigateur + Tailwind CSS,
  via CDN).
- `sw.js` : Service Worker offline (network-first sur la navigation,
  cache-first sur les assets).
- `manifest.json` : métadonnées PWA installable.
- Tables de données embarquées : `categories`, `allergens`,
  `equipment`, `tags`, `units`, `ingredients`, `recipes`. Champ
  `schema` à incrémenter en cas de changement structurel.

### Lancer en local
```bash
python3 -m http.server 8000
# puis http://localhost:8000
```
⚠️ Service Worker actif uniquement en HTTPS ou sur `localhost`.

### Versionnage — à bumper ENSEMBLE
À chaque release modifiant des ressources critiques :
- `<title>` dans `index.html`
- `CACHE_VERSION` dans `sw.js`

Sinon les utilisateurs gardent l'ancienne version en cache.

## Glossaire métier

- **IG** (Index Glycémique) : 0-100. IG bas ≤ 55.
- **CG** (Charge Glycémique) : IG pondéré par les glucides de la
  portion. Plus pertinent cliniquement que l'IG seul.
- **Batch cooking** : préparer plusieurs repas en une session.
- **SOPK** : Syndrome des Ovaires Polykystiques.
- **HACCP** : règles d'hygiène en restauration collective.
- **CGM** : capteur de glycémie continue.
- **RGPD** : Règlement Général sur la Protection des Données.
- **OMS** : Organisation Mondiale de la Santé.
- **ANSES / PNNS** : Agence française de sécurité sanitaire / Programme
  National Nutrition Santé.
- **EFSA** : European Food Safety Authority.
- **WCRF / AICR** : World Cancer Research Fund / American Institute
  for Cancer Research.
