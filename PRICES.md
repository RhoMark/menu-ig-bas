# Méthodologie des prix — Menu IG Bas

**Dernière mise à jour : 27 avril 2026 (V2.13.0)**

---

## 🎯 Objectif

Calculer le coût d'une recette à partir d'**un prix par ingrédient** sourcé et daté, plutôt que d'un coût figé par recette. Bénéfices :

- **Audit possible** : chaque prix a sa source (Open Prices, Carrefour Drive, INSEE, Que Choisir).
- **Cohérence** : deux recettes utilisant 100 g de poulet ont le même coût pour cet ingrédient.
- **Mise à jour groupée** : un prix qui change se propage à toutes les recettes qui l'utilisent.
- **Personnalisation future** (issue #16) : l'utilisateur pourra surcharger les prix qui ne correspondent pas à ses habitudes d'achat.

---

## 📊 Sources utilisées

### Couche 1 — Open Prices (32 ingrédients)

[**prices.openfoodfacts.org**](https://prices.openfoodfacts.org) — projet open source européen lancé fin 2024 par l'équipe Open Food Facts. Données crowdsourcées (utilisateurs scannent leurs tickets de caisse). License ODbL.

Pour chaque ingrédient, on a calculé la **médiane** sur les datapoints France des 6-12 derniers mois, après rejet des outliers (top/bottom 10 %).

Chaque entrée Open Prices porte la mention `Open Prices, médiane FR (N datapoints)` dans son champ `source`.

### Couche 2 — Carrefour Drive Q1 2026 (~80 ingrédients)

Pour les ingrédients qu'Open Prices ne couvre pas suffisamment (tags OFF inexistants ou peu denses), prix relevés sur Carrefour Drive Q1 2026, cross-checkés avec INSEE (indices alimentaires).

Source : `Carrefour Drive Q1 2026 (cross-check INSEE)`.

### Couche 3 — INSEE catégoriel (~25 ingrédients)

Pour les commodités (sel, sucre, oignon, etc.) où l'INSEE publie des indices catégoriels, on a utilisé ces moyennes nationales calibrées Q1 2026.

Source : `INSEE catégorie alimentaire Q1 2026`.

### Couche 4 — Estimations (~3 ingrédients)

Pour les rares ingrédients niche absents partout (ex: pak choï, certains exotiques), estimation Carrefour/Lidl Q1 2026 calibrée sur les données utilisateur réelles (×1.25 sur consommation 2026).

Source : `Estimation Carrefour/Lidl Q1 2026 (calibré utilisateur ×1.25)`.

---

## 🔢 Format de stockage

```json
{
  "id": "lentille verte",
  "price": 0.38,
  "unit": "100g",
  "source": "Open Prices, médiane FR (100 datapoints)",
  "updatedAt": "2026-04",
  "notes": "Optionnel : précisions"
}
```

- `id` : nom canonique de l'ingrédient (aligné sur la canonicalisation de `data-ingredients`)
- `price` : prix en euros
- `unit` : unité de référence (toujours `100g` pour le moment ; 1 ml ≈ 1 g pour les liquides)
- `source` : provenance auditable
- `updatedAt` : mois de la mise à jour (format `YYYY-MM`)
- `notes` : contexte additionnel optionnel

---

## ⚙️ Calcul d'un coût de recette

Le coût d'une recette est calculé à la volée (pas stocké) :

```
Pour chaque ingrédient (name, qty, unit) :
  1. Convertir qty en grammes (cf. dataRef.qtyToGrams)
  2. Lookup prix par canon → fallback sur strippé (cf. dataRef.price)
  3. Si trouvé : cost += (g / 100) × price
  4. Sinon : ingrédient marqué "missing", contribue à 0
Coverage = grammes_couverts / grammes_totaux
```

### Décision : computed vs legacy

```
Si coverage ≥ 80 % → on utilise le coût calculé (sources auditables)
Si coverage < 80 % → on retombe sur recipe.cost legacy (×1.25 calibré sur conso utilisateur)
```

Ce seuil garantit une transition douce de la V2.12 vers la V2.13. À mesure que le catalogue de prix s'étoffera, plus de recettes basculeront en mode calculé.

---

## ⚠️ Biais connu (V2.13.0)

Sur les 118 recettes actuellement en mode calculé, l'écart médian avec le legacy ×1.25 est de **-19 %**. Plusieurs hypothèses combinées :

1. **Open Prices est biaisé vers le bas** — les contributeurs scannent souvent les promos.
2. **Achats utilisateur premium** — les utilisateurs (et particulièrement HedgeX qui a calibré la V2.12) achètent peut-être des variantes AOP / bio / label rouge plus chères que la médiane retail.
3. **Couverture imparfaite** — les ingrédients premium d'une recette peuvent être les manquants, ce qui sous-estime leur impact.

**Conséquence** : les recettes en mode calculé affichent un coût ~15-20 % plus bas que la consommation réelle. Le coût *relatif* entre recettes reste cohérent (l'optimiseur budget continue de bien fonctionner). Le coût *absolu* affiché est inférieur au panier réel.

**Mitigation prévue** :
- **#16 (V3.x)** — saisie utilisateur des prix réels, qui surchargeront les valeurs par défaut.
- **Enrichissement progressif** de `data-prices` lors des sessions catalogue (cadence : après chaque release feature).

---

## 🔄 Évolution

Cette table est appelée à grossir et à être mise à jour régulièrement. Chaque entrée porte sa date (`updatedAt`) et sa source pour permettre :

- l'identification des prix obsolètes (typiquement > 12 mois)
- le tri par fraîcheur lors des audits
- la traçabilité en cas de contestation

À terme (après #16), un utilisateur pourra :
1. Voir tous les prix avec leurs sources
2. Surcharger localement ceux qui ne correspondent pas à ses achats réels
3. Conserver ces overrides chiffrés dans son profil

---

*Cette politique de prix est versionnée dans le code source. Toute modification passe par un commit public et est tracée dans l'historique git.*
