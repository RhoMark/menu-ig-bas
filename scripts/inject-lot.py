#!/usr/bin/env python3
"""inject-lot.py — Injecte un Lot de recettes dans le catalogue (data/recipes.js).

Usage :
    python3 scripts/inject-lot.py /tmp/lot95-recipes.py LOT95
    python3 scripts/inject-lot.py /tmp/lot95-recipes.py LOT95 --dry-run

- Charge la variable <VARNAME> (liste de dicts recette) depuis le fichier Python.
- Vérifie l'absence de collision d'ID avec le catalogue existant.
- Ré-émet le catalogue en JSON indent=2 (round-trip fidèle → diff minimal :
  seules les nouvelles recettes apparaissent, ajoutées en fin de tableau).
- NE bump PAS la version et NE touche PAS .expected-recipe-count (étapes suivantes
  du workflow blindé, cf. CLAUDE.md).
"""
import sys, argparse, importlib.util
from pathlib import Path
from recipes_store import load_recipes, dump_recipes, RECIPES_PATH


def load_var(pyfile: Path, varname: str):
    spec = importlib.util.spec_from_file_location("lotmod", pyfile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, varname):
        sys.exit(f"❌ variable {varname!r} absente de {pyfile}")
    return getattr(mod, varname)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pyfile", help="Fichier Python du Lot (ex: /tmp/lot95-recipes.py)")
    ap.add_argument("varname", help="Nom de la variable liste (ex: LOT95)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    new_recipes = load_var(Path(args.pyfile).resolve(), args.varname)
    data = load_recipes()
    existing_ids = {r["id"] for r in data["items"]}

    # Collision d'ID = stop dur.
    collisions = [r["id"] for r in new_recipes if r["id"] in existing_ids]
    if collisions:
        sys.exit(f"❌ collision d'ID avec le catalogue : {collisions}")
    # Doublons intra-lot.
    seen = set()
    for r in new_recipes:
        if r["id"] in seen:
            sys.exit(f"❌ ID dupliqué dans le lot : {r['id']}")
        seen.add(r["id"])

    before = len(data["items"])
    data["items"].extend(new_recipes)
    after = len(data["items"])


    print(f"  catalogue : {before} → {after} (+{after - before})")
    for r in new_recipes:
        print(f"    + {r['id']:6} {r['cuisine']:14} {r['type']:9} {r['name'][:52]}")

    if args.dry_run:
        print("  (dry-run : rien écrit)")
        return
    RECIPES_PATH.write_text(dump_recipes(data), encoding="utf-8")
    print(f"✅ injecté dans data/{RECIPES_PATH.name}")
    print(f"   → suite : bump-version, echo {after} > .expected-recipe-count, validate-recipe-data")


if __name__ == "__main__":
    main()
