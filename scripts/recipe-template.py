#!/usr/bin/env python3
"""recipe-template.py — Génère un skeleton de Lot prêt à éditer.

Usage :
    python3 scripts/recipe-template.py                              # interactif
    python3 scripts/recipe-template.py --lot 65 --cell italien/breakfast --count 2
    python3 scripts/recipe-template.py --lot 65 --brief             # depuis suggest-next-lot

Génère /tmp/lot{N}-recipes.py avec :
  - Skeletons commentés (rappel règles V2.43.0+, allergens, CG, etc.)
  - IDs auto-calculés depuis le catalogue existant
  - Cuisine/type pré-remplis
  - Liste des ingrédients data-glycemic existants à coller (rappel rapide)
  - Saisons pré-remplies depuis règle saisonnière
  - Instructions inline pour le suivant : lint → enrich → inject → commit
"""

import sys
import re
import json
import argparse
import datetime as dt
from pathlib import Path

# Map type → préfixe ID
TYPE_TO_PREFIX = {
    "breakfast": "b",
    "lunch":     "l",
    "dinner":    "d",
    "snack":     "s",
    "dessert":   "des",
}

VALID_CUISINES = ["francais", "italien", "mediterraneen", "asiatique",
                  "indien", "mexicain", "maghrebin", "universel"]

def upcoming_seasons(today=None):
    """Règle HedgeX : avril-juin → spring+summer ; juillet-sept → autumn+winter."""
    if today is None:
        today = dt.date.today()
    m = today.month
    if m in (4, 5, 6): return ["spring", "summer"]
    if m in (7, 8, 9): return ["autumn", "winter"]
    if m in (10, 11, 12): return ["winter", "spring"]
    return ["spring", "summer"]

def next_id_for_type(existing_recipes, type_):
    """Trouve le prochain ID pour un type donné (b101 si max(b) = b100)."""
    prefix = TYPE_TO_PREFIX[type_]
    max_n = 0
    pattern = re.compile(rf'^{prefix}(\d+)$')
    for r in existing_recipes:
        rid = r.get("id", "")
        m = pattern.match(rid)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return f"{prefix}{max_n + 1}"

def load_existing(repo_root):
    content = (Path(repo_root) / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data-recipes">\s*(\{.*?\})\s*</script>', content, re.DOTALL)
    recipes = json.loads(m.group(1))["items"]
    m = re.search(r'<script type="application/json" id="data-glycemic">\s*(\{.*?\})\s*</script>', content, re.DOTALL)
    glyc = json.loads(m.group(1))["items"]
    return recipes, glyc

# Snippet de recette à instancier
RECIPE_SKELETON = '''    {{
        "id": "{id}",
        "name": "{name_placeholder}",
        "type": "{type_}",
        "cuisine": "{cuisine}",
        "seasons": {seasons},  # ⚠ adapter si saison forcée (ex: ["summer"] pour pastèque)
        "prep": 15,            # minutes prép active
        "cook": 20,            # minutes cuisson passive
        "diff": 2,             # 1=facile / 2=moyen / 3=difficile
        "cost": 2.5,           # € par portion estimé
        "kcal": 350,           # kcal par portion (sera recalculé par Atwater si macros ok)
        "tags": [],            # vegetarian, vegan, festif, quick, no-cook, batch-friendly, light, kid-friendly, epicerie-specialisee
        "eq": [],              # stove, oven, blender, bowl, microwave, plancha, etc.
        "allergens": [],       # ⚠ DOIT correspondre aux ingrédients : eggs, lactose, gluten, fish, shellfish, nuts, soy, sesame, mustard
        # Si rest >= 120 minutes, ajouter "advance": "Xh au frais/congel"
        "ing": [
            # Format : [nom_qualifié, qty, unit, category]
            # ⚠ DÉNOMINATIONS QUALIFIÉES OBLIGATOIRES (CLAUDE.md V2.43.0+) :
            #   PAS "Lait" → "Lait demi-écrémé" / "Lait d'amande" / "Lait de coco"
            #   PAS "Riz"  → "Riz basmati complet" / "Riz long complet" / "Riz noir"
            #   PAS "Pâtes" → "Pâtes complètes" / "Pâtes de sarrasin"
            #   PAS "Farine" → "Farine T80 (semi-complète)" / "Farine de pois chiche"
            #   PAS "Yaourt" → "Yaourt nature" / "Yaourt grec"
            #   PAS "Beurre" → "Beurre doux" / "Beurre demi-sel"
            #   PAS "Pain" → "Pain complet" / "Pain au levain"
            #   PAS "Sucre" → "Sirop d'érable" / "Sucre roux" / "Sucre de coco"
            #   PAS "Huile" → "Huile d'olive" / "Huile de sésame" / "Huile de coco"
            # ⚠ Vérifier que chaque ingrédient existe dans data-glycemic (rappel à la fin du fichier)
            ["Ingrédient 1 qualifié", 100, "g", "produce"],
            ["Ingrédient 2 qualifié", 1, "u",  "dairy"],
        ],
        "steps": [
            # ⚠ STYLE "ADO QUI CUISINE" : gestes définis explicitement
            #   - "émincer" → "couper en fines lamelles"
            #   - "blanchir" → "plonger 30 sec dans l'eau bouillante, retirer"
            #   - "déglacer" → "verser un peu de liquide chaud pour décoller les sucs au fond"
            # ⚠ Repères visuels concrets : "jusqu'à ce que l'oignon devienne translucide"
            # Minimum 3 étapes (warning si <3, erreur si <2). Idéal : 6-10.
            "Étape 1...",
            "Étape 2...",
            "Étape 3...",
        ]
    }},
'''

# Cibles CG par mealType (CLAUDE.md V2.95.0)
CG_TARGETS = {
    "breakfast": "6-9 (cible 9, max 18 = bloqué par lint)",
    "lunch":     "12-14 (cible 14, max 28 = bloqué par lint)",
    "dinner":    "8-10 (cible 10, max 20 = bloqué par lint)",
    "snack":     "4-6 (cible 6, max 12 = bloqué par lint)",
    "dessert":   "< 8 (cible 8, max 16 = bloqué par lint)",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lot", type=int, required=True, help="Numéro du Lot (ex: 65)")
    parser.add_argument("--cell", default=None, help="Cellule cuisine/type (ex: italien/breakfast)")
    parser.add_argument("--count", type=int, default=2, help="Nombre de recettes à générer")
    parser.add_argument("--cells", default=None, help="Multi-cellules : 'italien/breakfast:2,asiatique/snack:3'")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    recipes, glyc = load_existing(repo_root)

    # Construire la liste des (cuisine, type, count)
    if args.cells:
        plan = []
        for item in args.cells.split(","):
            cell, count = item.split(":")
            cuisine, type_ = cell.strip().split("/")
            plan.append((cuisine, type_, int(count)))
    elif args.cell:
        cuisine, type_ = args.cell.split("/")
        plan = [(cuisine, type_, args.count)]
    else:
        print("❌ Fournir --cell cuisine/type OU --cells 'c1/t1:n1,c2/t2:n2'")
        sys.exit(2)

    # Calculer les IDs auto
    # On simule l'ajout au fur et à mesure pour éviter doublons intra-Lot
    skeletons_text = []
    fake_existing = list(recipes)
    seasons = upcoming_seasons()
    for cuisine, type_, count in plan:
        if cuisine not in VALID_CUISINES:
            print(f"⚠️  cuisine {cuisine!r} invalide, ignoré")
            continue
        if type_ not in TYPE_TO_PREFIX:
            print(f"⚠️  type {type_!r} invalide, ignoré")
            continue
        for _ in range(count):
            rid = next_id_for_type(fake_existing, type_)
            fake_existing.append({"id": rid})
            name_ph = f"{cuisine.capitalize()} {type_} #{rid}"
            skel = RECIPE_SKELETON.format(
                id=rid,
                name_placeholder=name_ph,
                type_=type_,
                cuisine=cuisine,
                seasons=json.dumps(seasons, ensure_ascii=False),
            )
            skeletons_text.append((rid, cuisine, type_, skel))

    # Rappel des ingrédients existants par catégorie (extrait court)
    glyc_names = sorted([it["id"] for it in glyc])
    sample_glyc = glyc_names[:30] + ["... +", f"{len(glyc_names) - 30} autres dans data-glycemic"]

    # Génère le fichier
    out_path = Path(f"/tmp/lot{args.lot}-recipes.py")
    header_planned = "\n".join(f"# - {c}/{t} × {n}" for c, t, n in plan)
    cg_lines = "\n".join(f"# - {t.ljust(10)}: {v}" for t, v in CG_TARGETS.items())
    glyc_sample = ", ".join(sample_glyc)
    lot_label = f"LOT{args.lot}"
    content = f'''"""Lot {args.lot} — V2.99.x — généré par recipe-template.py

Plan de ce Lot :
{header_planned}

═══════════════════════════════════════════════════════════════════════
📋 CHECKLIST avant de lancer le lint (à cocher mentalement) :
═══════════════════════════════════════════════════════════════════════

✅ NOMS QUALIFIÉS (V2.43.0+) — Pas de "Lait", "Riz", "Pâtes", "Farine",
   "Yaourt", "Beurre", "Pain", "Sucre", "Huile" seuls. Toujours qualifier.

✅ ALLERGENS COHÉRENTS avec les ing :
   - saumon/thon/etc. → fish
   - crevettes/moules/etc. → shellfish
   - œuf/jaune d'œuf → eggs
   - lait/yaourt/fromage/crème (sauf lait coco/amande/soja) → lactose
   - farine de blé/pâtes/pain/boulgour/couscous → gluten (PAS riz/maïs/sarrasin/pois chiche)
   - amande/noix/noisette/pistache/cajou/pécan → nuts
   - soja/tofu/tempeh/edamame → soy
   - sésame/tahin → sesame
   - moutarde → mustard

✅ TAGS COHÉRENTS :
   - vegan = aucun produit animal (pas fish/eggs/lactose)
   - vegetarian = peut contenir œufs/laitages (pas fish/shellfish)
   - quick = prep + cook ≤ 30 min
   - no-cook = cook = 0
   - batch-friendly = se garde 3-5j au frais
   - festif = apéro / brunch / occasion spéciale
   - light = kcal ≤ 200 par portion

✅ CG CIBLES PAR MEALTYPE (HedgeX V2.95.0) :
{cg_lines}

✅ rest ≥ 120 minutes → champ `advance` obligatoire (ex: "2h au frais")

✅ STYLE "ADO QUI CUISINE" : gestes définis, repères visuels concrets,
   pas d'implicite. 6-10 étapes typique. Minimum 3 (warning si <3).

✅ IG bas par ingrédient : préférer aliments < 55. Éviter pomme de terre
   crue blanche, riz blanc, pain blanc, sucre raffiné.

═══════════════════════════════════════════════════════════════════════
WORKFLOW POST-RÉDACTION :
═══════════════════════════════════════════════════════════════════════

1. python3 scripts/lint-new-recipes.py {out_path} --varname {lot_label}
2. (si manquants) python3 scripts/auto-enrich-glycemic.py {out_path} --apply
3. python3 scripts/lint-new-recipes.py {out_path} --varname {lot_label}   # re-check
4. python3 /tmp/inject-lot.py lot{args.lot}-recipes {lot_label}
5. bash scripts/bump-version.sh --auto patch
6. echo "<nouveau_count>" > .expected-recipe-count
7. python3 scripts/validate-recipe-data.py
8. git commit + push

═══════════════════════════════════════════════════════════════════════
ÉCHANTILLON INGRÉDIENTS data-glycemic disponibles ({len(glyc_names)} total) :
═══════════════════════════════════════════════════════════════════════
# {glyc_sample}
# → tape "grep id index.html | head -200" pour la liste complète
"""

{lot_label} = [
'''
    for rid, cuisine, type_, skel in skeletons_text:
        content += f"\n    # ═══ {rid} ({cuisine}/{type_}) ═══\n"
        content += skel

    content += "]\n\nif __name__ == '__main__':\n"
    content += f"    print(f'{{len({lot_label})}} recettes prêtes')\n"
    content += f"    for r in {lot_label}:\n"
    content += "        print(f'  {r[\"id\"]:6} {r[\"cuisine\"]:14} {r[\"type\"]:10} {r[\"name\"][:55]}')\n"

    out_path.write_text(content, encoding="utf-8")

    print(f"✅ Skeleton écrit : {out_path}")
    print(f"   {len(skeletons_text)} recettes à rédiger")
    print(f"   Prochaines étapes :")
    print(f"     1. Édite {out_path}")
    print(f"     2. python3 scripts/lint-new-recipes.py {out_path} --varname {lot_label}")
    print(f"     3. python3 scripts/auto-enrich-glycemic.py {out_path} --apply")


if __name__ == "__main__":
    main()
