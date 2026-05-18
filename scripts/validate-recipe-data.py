#!/usr/bin/env python3
"""validate-recipe-data.py — validation stricte du schéma des recettes.

Vérifie pour CHAQUE recette dans data-recipes :
  - Champs obligatoires
  - Vocabulary clos (type, cuisine, seasons, tags, eq, allergens, categories)
  - Cohérence sémantique (prep, cook, diff, kcal, ing, steps…)
  - Dénominations qualifiées (V2.43.0+ — règle non négociable CLAUDE.md)
  - rest >= 120 implique advance renseigné

Usage:
  python3 scripts/validate-recipe-data.py
  python3 scripts/validate-recipe-data.py --strict       # échec sur warnings
  python3 scripts/validate-recipe-data.py --recipe l190  # une seule
  python3 scripts/validate-recipe-data.py --json         # output JSON pour CI

Code retour:
  0 = OK (peut y avoir warnings)
  1 = erreurs fatales détectées
  2 = erreur d'entrée (fichier introuvable, etc.)
"""

import re
import sys
import json
import argparse
from pathlib import Path

# ── Vocabulaires clos (cf. CLAUDE.md V2.43.0+) ────────────────────────────

ALLOWED_TYPES = {"breakfast", "lunch", "dinner", "snack", "dessert"}
ALLOWED_CUISINES = {"francais", "italien", "mediterraneen", "asiatique",
                    "indien", "mexicain", "maghrebin", "universel"}
ALLOWED_SEASONS = {"spring", "summer", "autumn", "winter", "all"}
ALLOWED_TAGS = {"vegetarian", "vegan", "batch-friendly", "quick", "no-cook",
                "kid-friendly", "festif", "light", "apero-sec",
                "apero-dinatoire", "epicerie-specialisee"}
ALLOWED_EQUIPMENT = {"stove", "oven", "blender", "bowl", "pan", "grill",
                     "cast-iron", "steamer", "pressure-cooker", "microwave"}
ALLOWED_ALLERGENS = {"lactose", "gluten", "nuts", "eggs", "fish", "sesame",
                     "soy", "shellfish", "mustard", "egg"}
ALLOWED_CATEGORIES = {"produce", "pantry", "spices", "dairy", "meat-fish",
                      "bread", "frozen"}

# ── Dénominations qualifiées (CLAUDE.md, règle non-négociable) ────────────

# Termes interdits seuls (doivent être qualifiés)
GENERIC_TERMS_FORBIDDEN = {
    "lait": ["Lait demi-écrémé", "Lait écrémé", "Lait entier", "Lait d'amande", "Lait de coco"],
    "riz": ["Riz basmati complet", "Riz long complet", "Riz rond complet", "Riz brun"],
    "pâtes": ["Pâtes complètes", "Pâtes intégrales", "Pâtes de sarrasin"],
    "farine": ["Farine T80", "Farine T110", "Farine de pois chiche", "Farine d'épeautre"],
    "yaourt": ["Yaourt nature", "Yaourt grec", "Yaourt brassé"],
    "beurre": ["Beurre doux", "Beurre demi-sel", "Beurre clarifié"],
    "pain": ["Pain complet", "Pain au levain", "Pain de seigle", "Pain pita complet"],
    "sucre": ["Sucre roux", "Sucre de coco", "Miel", "Sirop d'érable"],
    "huile": ["Huile d'olive", "Huile de coco", "Huile de sésame", "Huile de noix"],
}

# Champs requis par recette
REQUIRED_FIELDS = {"id", "name", "type", "cuisine", "seasons", "prep",
                   "cook", "diff", "cost", "kcal", "tags", "eq",
                   "allergens", "ing", "steps"}


def extract_recipes(index_path):
    """Extrait data-recipes JSON depuis index.html."""
    with open(index_path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(
        r'<script type="application/json" id="data-recipes">\s*(.*?)\s*</script>',
        content, re.DOTALL)
    if not m:
        raise RuntimeError("Bloc data-recipes introuvable dans index.html")
    data = json.loads(m.group(1))
    return data.get("items", [])


def normalize_ing_name(name):
    """Normalise un nom d'ingrédient pour matcher les termes génériques.

    Strip accents, lowercase, retire (entre parenthèses) et descripteurs.
    """
    import unicodedata
    n = (name or "").strip().lower()
    n = "".join(ch for ch in unicodedata.normalize("NFD", n)
                if unicodedata.category(ch) != "Mn")
    # Retire (parenthèses)
    n = re.sub(r"\s*\([^)]*\)\s*", " ", n)
    # Retire descripteurs
    n = re.sub(r"\b(bio|frais|fraiche|jeune|petit|gros|nouveau)\b", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def validate_recipe(r):
    """Retourne (errors[], warnings[]) pour une recette."""
    errors = []
    warnings = []

    rid = r.get("id", "<no-id>")

    # ── 1. Champs obligatoires ─────────────────────────────────────────
    missing = REQUIRED_FIELDS - set(r.keys())
    for f in missing:
        errors.append(f"champ obligatoire manquant : '{f}'")

    if errors:  # pas la peine de continuer
        return errors, warnings

    # ── 2. Vocabulary clos ─────────────────────────────────────────────
    if r["type"] not in ALLOWED_TYPES:
        errors.append(f"type invalide '{r['type']}'")
    if r["cuisine"] not in ALLOWED_CUISINES:
        errors.append(f"cuisine invalide '{r['cuisine']}'")
    for s in r.get("seasons", []):
        if s not in ALLOWED_SEASONS:
            errors.append(f"season invalide '{s}'")
    for t in r.get("tags", []):
        if t not in ALLOWED_TAGS:
            errors.append(f"tag invalide '{t}'")
    for e in r.get("eq", []):
        if e not in ALLOWED_EQUIPMENT:
            errors.append(f"eq invalide '{e}'")
    for a in r.get("allergens", []):
        if a not in ALLOWED_ALLERGENS:
            errors.append(f"allergen invalide '{a}'")

    # ── 3. Cohérence sémantique ────────────────────────────────────────
    prep = r.get("prep", 0)
    cook = r.get("cook", 0)
    if prep + cook <= 0:
        errors.append(f"prep + cook = 0 (doit être >0)")
    if not isinstance(r.get("diff"), int) or r["diff"] not in {1, 2, 3}:
        errors.append(f"diff invalide '{r.get('diff')}' (doit être 1, 2 ou 3)")
    if r.get("cost", 0) <= 0:
        warnings.append(f"cost suspect : {r.get('cost')}")
    if r.get("kcal", 0) <= 0:
        warnings.append(f"kcal suspect : {r.get('kcal')}")
    # Ing : seuil 2 (erreur), warning si < 3 pour encourager des recettes étoffées
    if len(r.get("ing", [])) < 2:
        errors.append(f"ing trop court : {len(r.get('ing', []))} < 2")
    elif len(r.get("ing", [])) < 3:
        warnings.append(f"ing court : {len(r.get('ing', []))} (recommandé ≥3)")
    # Steps : seuil 2 (erreur), warning si < 3 pour encourager style ado-cuisine
    if len(r.get("steps", [])) < 2:
        errors.append(f"steps trop court : {len(r.get('steps', []))} < 2")
    elif len(r.get("steps", [])) < 3:
        warnings.append(f"steps court : {len(r.get('steps', []))} (style ado-cuisine recommande ≥3)")

    # ── 4. Structure ing[i] = [name, qty, unit, category] ──────────────
    for i, ing in enumerate(r.get("ing", [])):
        if not isinstance(ing, list) or len(ing) != 4:
            errors.append(f"ing[{i}] mal formé : {ing}")
            continue
        name, qty, unit, cat = ing
        if not isinstance(name, str) or not name:
            errors.append(f"ing[{i}].name vide ou pas string")
        if not isinstance(qty, (int, float)) or qty <= 0:
            errors.append(f"ing[{i}].qty invalide ({qty})")
        if not isinstance(unit, str):
            errors.append(f"ing[{i}].unit pas string")
        if cat not in ALLOWED_CATEGORIES:
            errors.append(f"ing[{i}].category '{cat}' invalide")

    # ── 5. Dénominations qualifiées (CLAUDE.md règle critique) ─────────
    for i, ing in enumerate(r.get("ing", [])):
        if not isinstance(ing, list) or len(ing) < 1:
            continue
        name = ing[0]
        normalized = normalize_ing_name(name)
        # Compare au mot exact (générique sans qualificatif)
        for generic, alternatives in GENERIC_TERMS_FORBIDDEN.items():
            if normalized == generic:
                # Mot générique seul, à qualifier
                alt_list = " / ".join(alternatives[:3])
                errors.append(
                    f"ing[{i}] '{name}' générique seul (V2.43.0+). "
                    f"Utiliser : {alt_list}…")

    # ── 6. rest >= 120 implique advance renseigné ──────────────────────
    rest = r.get("rest", 0)
    if rest and rest >= 120:
        if not r.get("advance"):
            warnings.append(f"rest={rest} min mais 'advance' non renseigné")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Valide le schéma des recettes")
    parser.add_argument("--strict", action="store_true",
                        help="échec sur warnings aussi")
    parser.add_argument("--recipe", type=str,
                        help="valide une recette par id")
    parser.add_argument("--json", action="store_true",
                        help="output JSON pour CI")
    parser.add_argument("--index", default=None,
                        help="path vers index.html (défaut : auto)")
    args = parser.parse_args()

    # Trouve index.html (parent du dossier scripts/)
    if args.index:
        index_path = Path(args.index)
    else:
        index_path = Path(__file__).resolve().parent.parent / "index.html"

    if not index_path.exists():
        print(f"❌ index.html introuvable : {index_path}", file=sys.stderr)
        sys.exit(2)

    try:
        recipes = extract_recipes(index_path)
    except Exception as e:
        print(f"❌ Extraction échouée : {e}", file=sys.stderr)
        sys.exit(2)

    if args.recipe:
        recipes = [r for r in recipes if r.get("id") == args.recipe]
        if not recipes:
            print(f"❌ Recette '{args.recipe}' introuvable", file=sys.stderr)
            sys.exit(2)

    # ── Validation ────────────────────────────────────────────────────
    all_results = []
    total_errors = 0
    total_warnings = 0

    for r in recipes:
        errors, warnings = validate_recipe(r)
        if errors or warnings:
            all_results.append({
                "id": r.get("id", "?"),
                "name": r.get("name", "?")[:50],
                "errors": errors,
                "warnings": warnings,
            })
            total_errors += len(errors)
            total_warnings += len(warnings)

    # ── Output ────────────────────────────────────────────────────────
    if args.json:
        print(json.dumps({
            "total_recipes": len(recipes),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "results": all_results,
        }, ensure_ascii=False, indent=2))
    else:
        for res in all_results:
            print(f"\n{res['id']:6} {res['name']}")
            for e in res["errors"]:
                print(f"  ❌ {e}")
            for w in res["warnings"]:
                print(f"  ⚠️  {w}")

        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Total : {len(recipes)} recettes")
        print(f"  Erreurs : {total_errors}")
        print(f"  Warnings : {total_warnings}")

    # ── Code retour ────────────────────────────────────────────────────
    if total_errors > 0:
        sys.exit(1)
    if args.strict and total_warnings > 0:
        sys.exit(1)
    if not args.json:
        print("✅ Validation OK")
    sys.exit(0)


if __name__ == "__main__":
    main()
