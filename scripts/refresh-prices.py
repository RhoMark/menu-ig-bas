#!/usr/bin/env python3
"""refresh-prices.py — Audit + alerte mensuelle sur la fraîcheur des prix.

Conçu pour tourner via GitHub Actions le 1er du mois. Pas d'auto-update
silencieuse : génère un rapport, et si nécessaire ouvre une issue GitHub
pour HedgeX afin qu'il valide les ajustements.

Tâches :
  1. Audit de l'âge des entrées data-prices (médiane, % >6 mois)
  2. Calcul théorique du facteur d'inflation alimentaire 2023→now en
     supposant une projection +1,5 % / an post-2024 (à valider INSEE
     manuellement)
  3. Suggestion de refresh si :
     - médiane updatedAt > 6 mois
     - >20 % des entrées > 9 mois
     - Le facteur d'inflation théorique diverge de >5 % du facteur câblé

Usage local :
    python3 scripts/refresh-prices.py             # audit silencieux
    python3 scripts/refresh-prices.py --verbose   # détaillé
    python3 scripts/refresh-prices.py --gh-output # format GH Actions

Important : ce script NE MODIFIE PAS automatiquement le code.
Pour update effectif, HedgeX ou Claude (en session) valide les chiffres
contre INSEE / Open Prices / Carrefour Drive et commit manuellement.
"""

import sys
import re
import json
import argparse
import datetime as dt
from collections import Counter
from pathlib import Path


def parse_date(s):
    """Parse '2026-04' ou '2026-05-12' → datetime."""
    if not s:
        return None
    try:
        if len(s) == 7:  # YYYY-MM
            return dt.datetime.strptime(s + "-01", "%Y-%m-%d")
        return dt.datetime.strptime(s[:10], "%Y-%m-%d")
    except Exception:
        return None


def months_between(a, b):
    if not a or not b:
        return None
    return (b.year - a.year) * 12 + (b.month - a.month)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--gh-output", action="store_true",
                        help="Format GitHub Actions (set output for workflow)")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    index = repo / "index.html"
    content = index.read_text(encoding="utf-8")

    m = re.search(
        r'<script type="application/json" id="data-prices">\s*(\{.*?\})\s*</script>',
        content, re.DOTALL)
    if not m:
        print("❌ data-prices introuvable")
        sys.exit(2)
    data = json.loads(m.group(1))
    items = data["items"]

    # 1. Audit âge
    today = dt.datetime.now()
    ages_months = []
    by_age = Counter()
    for it in items:
        d = parse_date(it.get("updatedAt"))
        months = months_between(d, today) if d else None
        if months is not None:
            ages_months.append(months)
            if months <= 3:
                by_age["≤ 3 mois (frais)"] += 1
            elif months <= 6:
                by_age["3-6 mois (acceptable)"] += 1
            elif months <= 9:
                by_age["6-9 mois (à surveiller)"] += 1
            elif months <= 12:
                by_age["9-12 mois (vieux)"] += 1
            else:
                by_age["> 12 mois (obsolète)"] += 1

    ages_months.sort()
    n = len(ages_months)
    median_age = ages_months[n // 2] if n else None
    pct_over_6mo = 100 * sum(1 for a in ages_months if a > 6) / n if n else 0
    pct_over_9mo = 100 * sum(1 for a in ages_months if a > 9) / n if n else 0

    # 2. Facteur d'inflation théorique (modèle simple)
    # 2023: +12,2 %, 2024: +1,3 %, projection 2025-2026 : ~+1,5 %/an
    # Source à actualiser : INSEE indice CPI alimentaire (mensuel)
    INFLATION_YEARS = {
        2023: 0.122,
        2024: 0.013,
        2025: 0.015,  # projection à valider INSEE chaque mois
        2026: 0.015,  # projection à valider INSEE chaque mois
    }
    factor = 1.0
    current_year = today.year
    for y in range(2023, current_year + 1):
        factor *= (1 + INFLATION_YEARS.get(y, 0.015))
    # Pondère l'année courante au prorata du mois
    if current_year in INFLATION_YEARS:
        # Annule la part non-écoulée de l'année courante
        unwind = (12 - today.month) / 12
        factor /= (1 + INFLATION_YEARS[current_year] * unwind)

    # Lit le coefficient câblé actuel
    m2 = re.search(r'FOOD_INFLATION_FACTOR_2023_TO_NOW\s*=\s*([\d.]+);', content)
    current_factor = float(m2.group(1)) if m2 else None

    # 3. Décisions
    actions = []
    if median_age is not None and median_age > 6:
        actions.append(f"📅 Médiane d'âge des prix : {median_age} mois (>6 mois) — refresh recommandé")
    if pct_over_9mo > 20:
        actions.append(f"⏰ {pct_over_9mo:.0f} % des prix sont >9 mois (seuil 20 %) — refresh urgent")
    if current_factor and abs(factor - current_factor) > 0.05:
        actions.append(f"📈 Facteur inflation théorique : {factor:.3f} vs câblé {current_factor:.3f} (écart >5 %) — update FOOD_INFLATION_FACTOR_2023_TO_NOW")

    # 4. Output
    print("=" * 64)
    print(f"refresh-prices.py — audit {today.strftime('%Y-%m-%d')}")
    print("=" * 64)
    print(f"Entrées data-prices analysées : {n}")
    print(f"Âge médian : {median_age} mois" if median_age is not None else "Âge médian : N/A")
    print(f"% >6 mois  : {pct_over_6mo:.0f} %")
    print(f"% >9 mois  : {pct_over_9mo:.0f} %")
    print()
    print("Distribution âge :")
    for k in ["≤ 3 mois (frais)", "3-6 mois (acceptable)", "6-9 mois (à surveiller)",
              "9-12 mois (vieux)", "> 12 mois (obsolète)"]:
        c = by_age[k]
        if c:
            print(f"  {k:30} {c:4} ({100*c/n:4.0f}%)")
    print()
    print(f"Facteur inflation câblé   : {current_factor}")
    print(f"Facteur inflation calculé : {factor:.3f}")
    print(f"  (2023×1.122 × 2024×1.013 × projection {today.year}-prorata)")
    print()

    if actions:
        print("🔔 ACTIONS RECOMMANDÉES :")
        for a in actions:
            print(f"  - {a}")
        print()
        if args.gh_output:
            # Format GitHub Actions output (write to GITHUB_OUTPUT if env)
            import os
            gh_out = os.environ.get("GITHUB_OUTPUT")
            if gh_out:
                with open(gh_out, "a") as f:
                    f.write("needs_refresh=true\n")
                    f.write(f"median_age={median_age}\n")
                    f.write(f"pct_over_9mo={pct_over_9mo:.0f}\n")
                    f.write(f"theoretical_factor={factor:.3f}\n")
                    f.write(f"current_factor={current_factor}\n")
                    summary = " ; ".join(actions).replace("\n", " ")
                    f.write(f"actions={summary}\n")
        sys.exit(1)
    else:
        print("✅ Aucune action requise — prix encore frais")
        if args.gh_output:
            import os
            gh_out = os.environ.get("GITHUB_OUTPUT")
            if gh_out:
                with open(gh_out, "a") as f:
                    f.write("needs_refresh=false\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
