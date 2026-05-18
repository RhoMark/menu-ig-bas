#!/usr/bin/env python3
"""suggest-next-lot.py — assistant rédaction du prochain Lot de recettes.

Analyse le catalogue existant et propose 12 recettes pour le prochain Lot :
  - Cellules cuisines × types les moins denses (vs cible 15+)
  - Saison à privilégier (selon date + règle mémoire saisonnalité)
  - Suggestions de noms-type
  - IDs prévus (l+next, d+next, etc.)
  - Tags suggérés (batch-friendly, vegan, etc.)

Output : brief markdown stdout + sauvegarde dans tâches/

Usage:
  python3 scripts/suggest-next-lot.py
  python3 scripts/suggest-next-lot.py --count 12
  python3 scripts/suggest-next-lot.py --target 18  # cible 18 recettes par cellule
"""

import re
import sys
import json
import argparse
import datetime as dt
from pathlib import Path
from collections import defaultdict

ALL_TYPES = ["breakfast", "lunch", "dinner", "snack", "dessert"]
ALL_CUISINES = ["francais", "italien", "mediterraneen", "asiatique",
                "indien", "mexicain", "maghrebin", "universel"]

# Préfixes IDs par type
ID_PREFIXES = {
    "breakfast": "b",
    "lunch": "l",
    "dinner": "d",
    "snack": "s",
    "dessert": "des",
}


def extract_recipes(index_path):
    with open(index_path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(
        r'<script type="application/json" id="data-recipes">\s*(.*?)\s*</script>',
        content, re.DOTALL)
    if not m:
        raise RuntimeError("data-recipes introuvable")
    return json.loads(m.group(1)).get("items", [])


def build_matrix(recipes):
    matrix = defaultdict(lambda: defaultdict(int))
    for r in recipes:
        matrix[r.get("cuisine", "?")][r.get("type", "?")] += 1
    return matrix


def max_id_for_type(recipes, type_):
    """Retourne le plus grand numéro d'ID pour un type donné."""
    prefix = ID_PREFIXES.get(type_, "")
    max_n = 0
    for r in recipes:
        if r.get("type") != type_:
            continue
        rid = r.get("id", "")
        # Extrait le suffixe numérique
        m = re.match(rf"^{prefix}(\d+)$", rid)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return max_n


def determine_season(today=None):
    """Saison à privilégier selon date courante (règle mémoire HedgeX).

    Avril-juin : printemps + été en cours
    Juillet+ : préparer automne + hiver (saison à venir)
    Octobre-décembre : automne + hiver
    Janvier-mars : printemps à venir
    """
    if today is None:
        today = dt.date.today()
    month = today.month
    if month in (4, 5, 6):
        return ["spring", "summer"]
    elif month in (7, 8, 9):
        return ["autumn", "winter"]  # préparer la saison à venir
    elif month in (10, 11, 12):
        return ["autumn", "winter"]
    else:  # 1, 2, 3
        return ["spring"]  # printemps à venir


def find_target_cells(matrix, target=15, max_cells=6):
    """Identifie les cellules cuisines × types sous le seuil cible."""
    candidates = []
    for c in ALL_CUISINES:
        for t in ALL_TYPES:
            count = matrix[c].get(t, 0)
            if count < target:
                gap = target - count
                candidates.append((c, t, count, gap))
    # Tri par gap descendant
    candidates.sort(key=lambda x: -x[3])
    return candidates[:max_cells]


def distribute_count(cells, total_count):
    """Distribue `total_count` recettes sur les cellules en proportion du gap."""
    if not cells:
        return []
    total_gap = sum(c[3] for c in cells)
    distrib = []
    remaining = total_count
    for i, (cuisine, type_, count, gap) in enumerate(cells):
        if i == len(cells) - 1:
            allocated = remaining
        else:
            allocated = max(1, round(total_count * gap / total_gap))
            allocated = min(allocated, remaining)
        if allocated > 0:
            distrib.append((cuisine, type_, count, allocated))
        remaining -= allocated
        if remaining <= 0:
            break
    return distrib


def suggest_recipe_names(cuisine, type_, count, season_hint):
    """Suggère des noms-type de recettes pour une cellule donnée."""
    # Templates par cuisine + type
    suggestions = {
        ("indien", "breakfast"): [
            "Porridge cardamome-mangue", "Upma de sarrasin", "Bowl chia yaourt-mangue",
            "Lassi salé concombre-menthe", "Idli au sarrasin",
        ],
        ("indien", "lunch"): [
            "Bowl dal jaune et riz basmati", "Salade tikka poulet-roquette",
            "Salade chaat pois chiches", "Bowl chana masala",
        ],
        ("indien", "dinner"): [
            "Curry de poulet épinards (saag)", "Tikka masala saumon",
            "Curry kerala lait de coco", "Dal makhani lentilles noires",
        ],
        ("indien", "snack"): [
            "Lassi salé concombre", "Pakoras allégés", "Houmous mixte épicé",
        ],
        ("indien", "dessert"): [
            "Lassi mangue rose", "Kheer riz cardamome", "Shrikhand safran",
        ],
        ("mexicain", "lunch"): [
            "Bowl burrito haricots noirs", "Salade fajita poulet",
            "Pozole verde poulet", "Sopa de lima",
        ],
        ("mexicain", "dinner"): [
            "Tinga de pollo chipotle", "Crevettes diabla", "Pollo asado",
            "Enchiladas suizas allégées",
        ],
        ("maghrebin", "lunch"): [
            "Salade fattouche aux pois chiches", "Taboulé maghrébin",
            "Bowl couscous d'orge complet", "Salade orange-fenouil chermoula",
        ],
        ("maghrebin", "dinner"): [
            "Tajine pois chiches-épinards", "Brochettes ras-el-hanout",
            "Loup au four citron-fenouil", "Tajine de sardines",
        ],
        ("francais", "breakfast"): [
            "Œuf coque et mouillettes complètes", "Tartine ricotta-figues",
            "Bircher muesli flocons sarrasin",
        ],
        ("italien", "breakfast"): [
            "Bowl yaourt-grenade-pistache", "Crostini ricotta-tomate",
        ],
        ("asiatique", "breakfast"): [
            "Congee riz brun aux œufs", "Bol soba froides au sésame",
        ],
        # Génériques fallback
        ("*", "breakfast"): ["Smoothie bowl", "Tartine complète", "Porridge"],
        ("*", "lunch"): ["Salade composée", "Bowl complet", "Wrap au"],
        ("*", "dinner"): ["Curry / tajine / sauté", "Poisson au four", "Plat mijoté"],
        ("*", "snack"): ["Mix énergie", "Houmous", "Smoothie"],
        ("*", "dessert"): ["Mousse", "Crème", "Verrine"],
    }

    key = (cuisine, type_)
    if key in suggestions:
        names = suggestions[key]
    else:
        names = suggestions.get(("*", type_), [f"Recette {cuisine} {type_}"])

    # Compose count noms en cyclant si nécessaire
    result = []
    for i in range(count):
        result.append(names[i % len(names)])
    return result


def build_brief(recipes, count, target):
    """Construit le brief markdown du prochain Lot."""
    matrix = build_matrix(recipes)
    cells = find_target_cells(matrix, target=target)
    distrib = distribute_count(cells, count)
    seasons = determine_season()

    # Trouve les IDs disponibles
    type_max_ids = {t: max_id_for_type(recipes, t) for t in ALL_TYPES}

    # Détermine le numéro de Lot
    # Cherche le dernier Lot dans les commits récents (heuristique : compte recettes / 12)
    next_lot = len(recipes) // 12 + 1

    today = dt.date.today().isoformat()

    lines = []
    lines.append(f"# Brief Lot {next_lot} — {today}")
    lines.append("")
    lines.append(f"**Catalogue actuel** : {len(recipes)} recettes")
    lines.append(f"**Cible cellules** : {target}+ recettes par cuisine × type")
    lines.append(f"**Saisons cibles** : {', '.join(seasons)} (selon date courante)")
    lines.append("")

    if not distrib:
        lines.append("✅ Toutes les cellules sont à ≥{target} recettes. Pas de focus prioritaire.")
        return "\n".join(lines)

    lines.append("## Distribution proposée")
    lines.append("")
    lines.append("| Cuisine | Type | Actuel | À ajouter |")
    lines.append("|---------|------|--------|-----------|")
    total_distrib = 0
    for cuisine, type_, current, allocated in distrib:
        lines.append(f"| {cuisine} | {type_} | {current} | **{allocated}** |")
        total_distrib += allocated
    lines.append(f"| | | | **Total : {total_distrib}** |")
    lines.append("")

    lines.append("## Recettes suggérées (à valider et adapter)")
    lines.append("")

    next_ids = dict(type_max_ids)
    for cuisine, type_, current, allocated in distrib:
        lines.append(f"### {cuisine} / {type_} (+{allocated})")
        names = suggest_recipe_names(cuisine, type_, allocated, seasons)
        for name in names:
            next_ids[type_] += 1
            prefix = ID_PREFIXES[type_]
            new_id = f"{prefix}{next_ids[type_]}"
            lines.append(f"- **{new_id}** — {name} (cuisine: {cuisine}, "
                         f"seasons: {seasons}, tags: à définir)")
        lines.append("")

    lines.append("## Caractéristiques transversales recommandées")
    lines.append("")
    lines.append(f"- Saisonnalité : {', '.join(seasons)}")
    lines.append("- IG bas : CG ≤ 12 sur lunch/dinner, ≤ 8 sur snack/dessert")
    lines.append("- Allergens documentés à 100 %")
    lines.append("- Style \"ado qui cuisine\" : gestes définis, repères visuels")
    lines.append("- Ingrédients qualifiés (V2.43.0+) : pas de \"Lait\" seul, etc.")
    lines.append("- rest/advance renseignés si rest ≥ 120 min")
    lines.append("- Mix tags : ≥30 % batch-friendly, ≥20 % vegetarian, qq quick")
    lines.append("")

    lines.append("## Workflow d'exécution suggéré")
    lines.append("")
    lines.append("1. Valider la liste ci-dessus (remplacer noms si besoin)")
    lines.append("2. Rédiger les recettes dans `/tmp/lot{0}-recipes.py` (style des Lots précédents)".format(next_lot))
    lines.append("3. Script `scripts/validate-recipe-data.py` pour pré-flight check")
    lines.append("4. Injection via script Python dans `index.html`")
    lines.append("5. `./scripts/bump-version.sh patch` ou minor")
    lines.append("6. Commit format : `V2.X.X — Lot {0} : <thème>`".format(next_lot))
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=12,
                        help="nombre de recettes à proposer (défaut 12)")
    parser.add_argument("--target", type=int, default=15,
                        help="cible recettes par cellule (défaut 15)")
    parser.add_argument("--output", type=str,
                        help="path output (défaut : tâches/next-lot-brief-YYYY-MM-DD.md)")
    parser.add_argument("--stdout", action="store_true",
                        help="affiche au lieu de fichier")
    args = parser.parse_args()

    index_path = Path(__file__).resolve().parent.parent / "index.html"
    recipes = extract_recipes(index_path)
    brief = build_brief(recipes, args.count, args.target)

    if args.stdout:
        print(brief)
    else:
        if args.output:
            out_path = Path(args.output)
        else:
            today = dt.date.today().isoformat()
            out_path = (Path(__file__).resolve().parent.parent / "tâches"
                        / f"next-lot-brief-{today}.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(brief, encoding="utf-8")
        print(f"✅ Brief généré : {out_path}")


if __name__ == "__main__":
    main()
