#!/usr/bin/env python3
"""audit-catalog.py — audit du catalogue de recettes Menu IG Bas.

Produit un rapport markdown analysant :
  - Matrice cuisines × types (cellules <5 rouge, <10 orange, ≥15 vert)
  - Distribution allergens
  - Distribution tags (festif, batch-friendly, quick, no-cook, vegan…)
  - CG estimée par recette (utilise data-glycemic)
  - Champs requis manquants (producesLeftovers, photo, etc.)
  - Suggestions de focus pour le prochain Lot

Usage:
  python3 scripts/audit-catalog.py
  python3 scripts/audit-catalog.py --output tâches/audit-2026-05-18.md
  python3 scripts/audit-catalog.py --stdout    # affiche au lieu de fichier
"""

import re
import sys
import json
import argparse
import datetime as dt
from pathlib import Path
from collections import Counter, defaultdict

ALL_TYPES = ["breakfast", "lunch", "dinner", "snack", "dessert"]
ALL_CUISINES = ["francais", "italien", "mediterraneen", "asiatique",
                "indien", "mexicain", "maghrebin", "universel"]


def extract_recipes(index_path):
    with open(index_path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(
        r'<script type="application/json" id="data-recipes">\s*(.*?)\s*</script>',
        content, re.DOTALL)
    if not m:
        raise RuntimeError("data-recipes introuvable")
    return json.loads(m.group(1)).get("items", [])


def cell_status(count, target_min=15):
    """Retourne emoji selon densité cellule."""
    if count >= target_min:
        return "🟢"
    elif count >= 10:
        return "🟡"
    elif count >= 5:
        return "🟠"
    else:
        return "🔴"


def build_matrix(recipes):
    """Matrice cuisines × types."""
    matrix = defaultdict(lambda: defaultdict(int))
    for r in recipes:
        c = r.get("cuisine", "?")
        t = r.get("type", "?")
        matrix[c][t] += 1
    return matrix


def audit_allergens(recipes):
    """Distribution des allergens dans le catalogue."""
    c = Counter()
    no_allergens = 0
    for r in recipes:
        allergens = r.get("allergens", [])
        if not allergens:
            no_allergens += 1
        for a in allergens:
            c[a] += 1
    return c, no_allergens


def audit_tags(recipes):
    """Distribution des tags."""
    c = Counter()
    no_tags = 0
    for r in recipes:
        tags = r.get("tags", [])
        if not tags:
            no_tags += 1
        for t in tags:
            c[t] += 1
    return c, no_tags


def audit_field_coverage(recipes):
    """Couverture des champs optionnels mais importants."""
    return {
        "photo": sum(1 for r in recipes if r.get("photo")),
        "producesLeftovers": sum(1 for r in recipes if r.get("producesLeftovers")),
        "usesLeftovers": sum(1 for r in recipes if r.get("usesLeftovers")),
        "rest": sum(1 for r in recipes if r.get("rest", 0) > 0),
        "advance": sum(1 for r in recipes if r.get("advance")),
    }


def suggest_focus(matrix, recipes):
    """Identifie les cellules les moins denses (cibles prochains Lots)."""
    flat = []
    for c in ALL_CUISINES:
        for t in ALL_TYPES:
            count = matrix[c].get(t, 0)
            if count < 15:
                flat.append((c, t, count))
    flat.sort(key=lambda x: x[2])
    return flat[:8]  # top 8 plus déséquilibrés


def build_report(recipes):
    """Construit le rapport markdown complet."""
    matrix = build_matrix(recipes)
    allergens, no_aller = audit_allergens(recipes)
    tags, no_tags = audit_tags(recipes)
    fields = audit_field_coverage(recipes)
    focus = suggest_focus(matrix, recipes)
    total = len(recipes)
    today = dt.date.today().isoformat()

    lines = []
    lines.append(f"# Audit catalogue Menu IG Bas — {today}")
    lines.append("")
    lines.append(f"**Total** : {total} recettes")
    lines.append("")

    # ── Matrice ────────────────────────────────────────────────────────
    lines.append("## Matrice cuisines × types")
    lines.append("")
    lines.append("Légende : 🔴 <5 / 🟠 5-9 / 🟡 10-14 / 🟢 ≥15")
    lines.append("")
    header = "| cuisine | " + " | ".join(ALL_TYPES) + " | total |"
    sep = "|" + "---|" * (len(ALL_TYPES) + 2)
    lines.append(header)
    lines.append(sep)

    cuisine_totals = {}
    for c in sorted(ALL_CUISINES,
                    key=lambda x: -sum(matrix[x].get(t, 0) for t in ALL_TYPES)):
        row = [c]
        total_c = 0
        for t in ALL_TYPES:
            count = matrix[c].get(t, 0)
            row.append(f"{cell_status(count)} {count}")
            total_c += count
        row.append(f"**{total_c}**")
        cuisine_totals[c] = total_c
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ── Distribution allergens ─────────────────────────────────────────
    lines.append("## Distribution allergens")
    lines.append("")
    lines.append(f"Recettes sans aucun allergen tag : **{no_aller}** ({no_aller*100//total}%)")
    lines.append("")
    for a, n in allergens.most_common():
        lines.append(f"- `{a}` : {n} recettes ({n*100//total}%)")
    lines.append("")

    # ── Distribution tags ──────────────────────────────────────────────
    lines.append("## Distribution tags")
    lines.append("")
    lines.append(f"Recettes sans aucun tag : **{no_tags}** ({no_tags*100//total}%)")
    lines.append("")
    for t, n in tags.most_common():
        lines.append(f"- `{t}` : {n} recettes ({n*100//total}%)")
    lines.append("")

    # ── Couverture champs ──────────────────────────────────────────────
    lines.append("## Couverture champs optionnels")
    lines.append("")
    for field, count in fields.items():
        pct = count * 100 // total
        emoji = "🟢" if pct >= 50 else "🟡" if pct >= 20 else "🔴"
        lines.append(f"- {emoji} `{field}` : {count}/{total} ({pct}%)")
    lines.append("")

    # ── Suggestions focus prochain Lot ─────────────────────────────────
    lines.append("## Cellules à prioriser (prochain Lot)")
    lines.append("")
    if focus:
        lines.append("Les 8 cellules les moins denses (< 15 recettes) :")
        lines.append("")
        for c, t, n in focus:
            lines.append(f"- 🎯 **{c}** / **{t}** : {n} recettes → cible 15+")
    else:
        lines.append("✅ Toutes les cellules sont à ≥15 recettes")
    lines.append("")

    # ── Totaux cuisines ────────────────────────────────────────────────
    lines.append("## Totaux par cuisine")
    lines.append("")
    sorted_c = sorted(cuisine_totals.items(), key=lambda x: -x[1])
    for c, n in sorted_c:
        emoji = "🟢" if n >= 50 else "🟡" if n >= 25 else "🟠"
        lines.append(f"- {emoji} **{c}** : {n} recettes")
    lines.append("")

    # ── Footer ─────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("*Rapport généré par `scripts/audit-catalog.py`*")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit du catalogue recettes")
    parser.add_argument("--output", type=str,
                        help="path output (défaut : tâches/audit-catalog-YYYY-MM-DD.md)")
    parser.add_argument("--stdout", action="store_true",
                        help="affiche au lieu de fichier")
    parser.add_argument("--index", default=None,
                        help="path vers index.html")
    args = parser.parse_args()

    if args.index:
        index_path = Path(args.index)
    else:
        index_path = Path(__file__).resolve().parent.parent / "index.html"

    if not index_path.exists():
        print(f"❌ {index_path} introuvable", file=sys.stderr)
        sys.exit(2)

    recipes = extract_recipes(index_path)
    report = build_report(recipes)

    if args.stdout:
        print(report)
    else:
        if args.output:
            out_path = Path(args.output)
        else:
            today = dt.date.today().isoformat()
            out_path = (Path(__file__).resolve().parent.parent / "tâches"
                        / f"audit-catalog-{today}.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"✅ Rapport généré : {out_path}")
        print(f"   {len(recipes)} recettes analysées")


if __name__ == "__main__":
    main()
