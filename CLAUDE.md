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

### Dénominations d'ingrédients (V2.43.0+)
**Règle non négociable** : un ingrédient affiché dans la liste de
courses doit être **immédiatement actionnable au magasin**, sans
revenir à la recette pour comprendre ce qu'il faut acheter.

**Termes à toujours qualifier** (jamais de version générique seule
dans le champ `ing[0]` d'une recette) :

| Générique (interdit) | Préciser parmi |
|---|---|
| `Lait` | `Lait demi-écrémé`, `Lait écrémé`, `Lait entier`, `Lait d'amande`, `Lait de coco` |
| `Riz` | `Riz basmati complet`, `Riz long complet`, `Riz rond complet`, `Riz brun` |
| `Pâtes` | `Pâtes complètes`, `Pâtes intégrales`, `Pâtes de sarrasin` |
| `Farine` | `Farine T80 (semi-complète)`, `Farine T110`, `Farine de pois chiche`, `Farine d'épeautre` |
| `Yaourt` | `Yaourt nature`, `Yaourt grec`, `Yaourt brassé` |
| `Beurre` | `Beurre doux`, `Beurre demi-sel`, `Beurre clarifié` |
| `Pain` | `Pain complet`, `Pain au levain`, `Pain de seigle`, `Pain pita complet` |
| `Sucre` | `Sucre roux`, `Sucre de coco`, `Miel`, `Sirop d'érable` (préférer pour IG bas) |
| `Huile` | `Huile d'olive`, `Huile de coco`, `Huile de sésame`, `Huile de noix` |

Si une recette tolère plusieurs variantes, l'écrire explicitement :
`Lait demi-écrémé (ou boisson d'amande)`. La canonicalisation
(`canonicalName`) supprime les parenthèses pour l'agrégation, mais
le label affiché conserve l'option pour l'utilisateur.

### Cuisines (taxonomie V2.39.0+, issue #2)
8 cuisines fermées dans `data-cuisines` : `francais`, `italien`,
`mediterraneen`, `asiatique`, `indien`, `mexicain`, `maghrebin`,
`universel` (= fusion + recettes sans signature culturelle).
Chaque recette a un champ `cuisine: "<id>"` (singleton).

**Règles de maintenance** (à appliquer à chaque Lot de recettes) :

1. **Tagger toutes les nouvelles recettes** au moment de la rédaction.
   Le champ `cuisine` est obligatoire. Validation runtime
   `validateCuisineDistribution` log la distribution au boot.
2. **Pousser les cuisines sous-représentées** pour préserver
   l'équilibre, afin qu'aucun utilisateur ne se retrouve avec un pool
   trop maigre s'il sélectionne une cuisine en préférée. Cible
   pratique : **≥ 15 recettes par cuisine** (hors universel). Les Lots
   futurs doivent prioriser les cuisines sous ce seuil avant les
   cuisines déjà denses.
3. **Extraction d'une nouvelle cat** : si au sein d'une cuisine
   existante une sous-catégorie atteint **≥ 15 recettes** clairement
   identifiables (ex : « vietnamien » au sein d'« asiatique »),
   proposer l'extraction en cuisine distincte avec re-tagging.
4. **Universel < 35 %** du catalogue. Au-delà, audit nécessaire :
   beaucoup de recettes peuvent être taggées avec une cuisine plus
   précise (la console.warn signale ces déséquilibres).

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

## Charge glycémique journalière — référence Harvard

L'ANSES, le PNNS, l'EFSA et l'OMS **n'ont pas de seuil quantitatif
officiel** sur la CG quotidienne. Le projet retient la référence la
plus citée dans la littérature scientifique internationale (Harvard
School of Public Health, cohérente avec Glycemic Index Foundation
Sydney) :

- **CG / jour < 80** : bas (cible)
- **80 ≤ CG / jour ≤ 120** : modéré (acceptable, à limiter à 2 jours / semaine)
- **CG / jour > 120** : élevé (à éviter)

Ces seuils complètent les seuils par recette déjà câblés dans le code
(`glycemicTier()` : ≤ 10 bas, 11-19 modéré, ≥ 20 élevé). Pour qu'une
journée 5-services tienne sous 80, viser des CG individuelles :
breakfast 6-9, lunch / dinner 10-12, snack 4-6, dessert < 8.

## Profils santé et adaptation des seuils

La spec V1 §3.4 prévoit la prise en compte de pathologies : diabète T1
et T2, insulinorésistance, SOPK, grossesse / diabète gestationnel,
hypertension, dyslipidémies. Le projet ajoute aussi : rééquilibrage,
prévention cardiovasculaire, sportif endurance, sportif force, sain.

Seuils CG / jour par profil (sources : Harvard, ADA, GIF Sydney,
Cochrane reviews SOPK, FIGO grossesse) :

| Profil                  | Bas | Modéré  | Élevé   |
|-------------------------|-----|---------|---------|
| Diabète T2              | <80 | 80-100  | >100    |
| Insulinorésistance      | <80 | 80-100  | >100    |
| SOPK                    | <80 | 80-100  | >100    |
| Diabète gestationnel    | <80 | 80-100  | >100    |
| Diabète T1              | <100| 100-130 | >130    |
| Dyslipidémies           | <100| 100-120 | >120    |
| Hypertension            | <100| 100-120 | >120    |
| Rééquilibrage / surpoids| <100| 100-120 | >120    |
| Prévention cardio       | <100| 100-120 | >120    |
| Sportif force           | <130| 130-180 | >180    |
| Sportif endurance       | n/a | n/a     | n/a     |
| Sain (par défaut)       | <120| 120-150 | >150    |

**Sportif endurance** : seuil CG total non pertinent — le critère est
le **timing** des glucides (élevé pendant et juste après l'effort,
modéré sinon). Ce profil est exclu du calcul de seuil familial.

**Hypertension** : la CG est secondaire ; le vrai garde-fou est le
**sel ≤ 5 g / jour** (OMS). À implémenter en complément du garde-fou
CG (cf chantier V2.22.0+ enrichissement nutritionnel macros).

**Dyslipidémies** : la CG est secondaire ; le vrai garde-fou est les
**acides gras saturés < 10 % AET** + **fibres ≥ 25 g / jour**
(EFSA). Idem, à implémenter en complément.

### Logique foyer — le profil le plus contraignant gagne

```
seuil_famille_CG = MIN(seuil_CG_par_membre)
```

Un menu compatible avec le membre le plus contraignant convient
automatiquement à tous les autres ; l'inverse est faux. Même logique
que pour les allergènes (déjà en place).

Exemple : foyer 2 adultes (sain × 1, SOPK × 1) + 2 ados (sain × 2)
→ seuil famille = 80 CG / jour (cf SOPK).

### Limites et évolution

Ces seuils sont des **références de consensus international**, pas
des normes officielles ANSES / PNNS. À mentionner dans l'UX ("Source :
Harvard School of Public Health, GIF Sydney") et à laisser
configurable au niveau du membre pour les cas où un suivi médical
personnalisé recommande un autre seuil.

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

### Tailwind CSS — rebuild après changement de classes (V2.87.0, issue #94)
Tailwind est bundlé localement (`tailwind.css`), plus de dépendance CDN.
Quand on **ajoute / supprime des classes Tailwind** dans `index.html`, il
faut rebuild le CSS sinon les nouvelles classes n'auront pas d'effet :
```bash
npx tailwindcss -i ./tailwind-input.css -o ./tailwind.css --minify
```
Le scan se base sur `content: ["./index.html"]` (cf. `tailwind.config.js`).
**Commiter `tailwind.css` à chaque rebuild** — c'est ce fichier que les
utilisateurs reçoivent via GitHub Pages.

Si tu utilises uniquement des classes déjà présentes ailleurs dans le
fichier (cas le plus fréquent), pas besoin de rebuild — elles sont déjà
incluses.

`node_modules/` est ignoré via `.gitignore`. Pour cloner et builder :
```bash
npm install
npx tailwindcss -i ./tailwind-input.css -o ./tailwind.css --minify
```

### Versionnage — à bumper ENSEMBLE
À chaque release modifiant des ressources critiques :
- `<title>` dans `index.html`
- `CACHE_VERSION` dans `sw.js`

Sinon les utilisateurs gardent l'ancienne version en cache.

**Le footer UI et `appVersion` (logique d'import) lisent la version
dynamiquement depuis `document.title` — pas de bump manuel à faire**
(régression réparée en V2.19.2 après 3 oublis successifs).
Vérification : `grep -nE 'V\d+\.\d+\.\d+' index.html sw.js` doit ne
matcher que les 2 endroits ci-dessus + des commentaires d'historique.

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
