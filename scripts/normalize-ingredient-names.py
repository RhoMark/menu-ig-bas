#!/usr/bin/env python3
"""normalize-ingredient-names.py — V2.140.0 : un article = un nom = une ligne
dans la liste de courses.

Retour HedgeX (2026-11-21, captures) : « Crème fraîche liquide » et « Crème
liquide légère » sur 2 lignes, « Persil frais » / « Persil plat », « Bâton de
cannelle » / « Cannelle (bâton) », et « Sel, poivre » compté comme UN seul
ingrédient. Ce script corrige les recettes (data/recipes.js) :

  1. COMPOSÉS → séparés : « Sel, poivre » → « Sel » + « Poivre noir ». Le sel
     garde la quantité d'origine (le garde-fou sel ≤ 5 g/jour la comptait
     déjà comme du sel), les autres composants prennent 1 pincée (1 feuille
     pour le laurier).
  2. SYNONYMES → un nom unique (table RENAMES, gardée dans vocab.py pour que
     le lint bloque leur retour).
  3. « frais / fraîche » retiré quand le même article existe sans ce mot dans
     le même rayon (« Framboises fraîches » = « Framboises »).
  4. UNITÉS sans conversion possible ramenées à une unité convertible
     (UNIT_FIXES), pour que la fusion de la liste de courses puisse les additionner.
  5. RAYON : un même article est rangé dans le rayon où il l'est le plus souvent.

Usage : python3 scripts/normalize-ingredient-names.py [--apply]
Sans --apply : affiche ce qui changerait.
"""
import collections
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recipes_store as rs  # noqa: E402
from vocab import INGREDIENT_RENAMES  # noqa: E402

# ── 1. Composés ────────────────────────────────────────────────────────────
COMPONENTS = {
    "sel": ("Sel", None),                      # None = garde la quantité d'origine
    "fleur de sel": ("Fleur de sel", None),
    "poivre": ("Poivre noir", (1, "pincée")),
    "muscade": ("Muscade", (1, "pincée")),
    "thym": ("Thym séché", (1, "pincée")),
    "laurier": ("Feuille de laurier", (1, "feuille")),
    "romarin": ("Romarin séché", (1, "pincée")),
    "cumin": ("Cumin moulu", (1, "pincée")),
    "origan séché": ("Origan séché", (1, "pincée")),
    "basilic séché": ("Basilic séché", (1, "pincée")),
    "sauge fraîche": ("Sauge fraîche", (1, "feuille")),
}
SALTS = {"sel", "fleur de sel"}

# ── 4. Unités : (nom après renommage, unité) → (nouvelle quantité = f(q), unité)
UNIT_FIXES = {
    ("Amandes effilées", "u"): (lambda q: q * 5, "g"),
    ("Amande effilée", "u"): (lambda q: q * 5, "g"),
    ("Tomatille", "g"): (lambda q: q / 40, "u"),                # 1 tomatille ≈ 40 g (ordre de grandeur)
    ("Piment guajillo séché", "g"): (lambda q: q / 5, "u"),    # 1 piment guajillo séché ≈ 5 g (ordre de grandeur)
    ("Piment jalapeño", "g"): (lambda q: q / 20, "u"),          # 1 jalapeño ≈ 20 g (ordre de grandeur)
    ("Piment rouge frais", "g"): (lambda q: q / 10, "u"),       # 1 piment rouge ≈ 10 g (ordre de grandeur)          # 1 « u » saisi = 1 petite poignée ≈ 5 g (ordre de grandeur)
    ("Feuille de gélatine", "u"): (lambda q: q, "feuille"),
    ("Feuille de nori", "u"): (lambda q: q, "feuille"),
    ("Gousse de vanille", "u"): (lambda q: q, "gousse"),
    ("Anis étoilé", "u"): (lambda q: q, "étoile"),
    ("Cannelle en bâton", "u"): (lambda q: q, "bâton"),
    ("Cannelle en bâton", "g"): (lambda q: q / 3, "bâton"),     # 1 bâton ≈ 3 g (même valeur que dataRef.qtyToGrams)
    ("Feuilles de curry", "u"): (lambda q: q, "feuille"),
    ("Feuille de laurier", "u"): (lambda q: q, "feuille"),
    ("Clou de girofle", "g"): (lambda q: max(1, round(q / 0.1)), "u"),  # 1 clou ≈ 0,1 g (ordre de grandeur)
    ("Fève tonka", "g"): (lambda q: q / 1.5, "u"),              # 1 fève ≈ 1,5 g (ordre de grandeur)
    ("Citronnelle", "branche"): (lambda q: q, "u"),
    ("Citronnelle", "g"): (lambda q: q / 20, "u"),              # 1 tige ≈ 20 g (ordre de grandeur)
    ("Pak choï", "u"): (lambda q: q * 50, "g"),                 # 1 mini pak choï ≈ 50 g (ordre de grandeur)
    ("Pomelo", "g"): (lambda q: q / 1000, "u"),                 # 1 pomelo ≈ 1 kg (ordre de grandeur)
    ("Salade laitue", "g"): (lambda q: q / 300, "u"),           # 1 laitue ≈ 300 g (ordre de grandeur)
    ("Zeste de citron", "u"): (lambda q: q * 2, "g"),           # zeste d'1 citron ≈ 2 g
    ("Zeste de citron vert", "u"): (lambda q: q * 2, "g"),
    ("Poivre noir en grains", "u"): (lambda q: q * 0.05, "g"),  # 1 grain ≈ 0,05 g
    ("Sardines fraîches", "g"): (lambda q: q / 80, "u"),        # même poids que data-ingredients (80 g)
    ("Cardamome en gousses", "u"): (lambda q: q, "gousse"),
    ("Feuille de laurier", "g"): (lambda q: max(1, round(q / 0.2)), "feuille"),  # 1 feuille ≈ 0,2 g (HERB_FEUILLE_G)
}

# Rayon imposé quand la majorité des recettes se trompe de rayon.
CATEGORY_OVERRIDES = {
    "Glaçons": "frozen", "Pulpe d'açaï surgelée": "frozen", "Edamame écossés": "frozen",
    "Raisins secs": "pantry", "Lait de coco": "pantry",
    "Pain de seigle": "bread", "Pain au levain (en tranches)": "bread",
    "Galette de sarrasin (toute prête)": "bread", "Feuille de brick": "bread", "Feuilles de brick": "bread",
    "Jus de citron vert": "produce",
    "Anchois à l'huile (facultatif)": "pantry",
    "Maïs en grains (frais ou surgelé)": "frozen", "Maïs en grains (boîte sans sucre)": "pantry",
    "Maïs en grains (hominy pour pozole)": "pantry",
}

# Même article (nom sans parenthèses) → un seul rayon, quelle que soit la précision
# entre parenthèses (« Lait de coco » et « Lait de coco (cuisine) »).
CATEGORY_BY_BASE = {
    "Lait de coco": "pantry", "Thon au naturel": "pantry", "Lait de coco cuisine": "pantry", "Houmous": "dairy",
    "Pain au levain": "bread", "Pain au levain rassis": "bread", "Pain complet": "bread", "Pain de seigle": "bread",
    "Tortilla maïs": "bread", "Tortilla de maïs": "bread", "Pâte à gyoza": "bread", "Pâtes à gyoza": "bread",
    "Citron confit": "pantry", "Citrons confits": "pantry", "Biscuit cuillère": "pantry", "Biscuits cuillère": "pantry",
    "Pâte d'achiote": "spices", "Bouquet garni": "produce", "Maïs doux": "pantry",
    "Dattes Medjool": "pantry", "Dattes Medjool dénoyautées": "pantry", "Falafels": "pantry",
    "Haricots verts": "produce", "Mangue": "produce", "Mangue surgelée": "frozen",
    "Piment guajillo séché": "spices",
    "Fruits rouges": "produce", "Fruits rouges surgelés": "frozen",
}

# Renommage qui dépend de l'unité (« Cannelle » 1 bâton = la cannelle en bâton, pas en poudre).
NAME_UNIT_RENAMES = {
    ("Cannelle", "bâton"): "Cannelle en bâton",
}


def strip_accents(s):
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()


FRAIS_RE = re.compile(r"\s+(frais|fraîche|fraîches|fraiche|fraiches)\b(?![^()]*\))", re.I)


def base_of(name):
    """Nom sans la précision entre parenthèses : « Citronnelle (tige fraîche) » → « Citronnelle »."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def key_of(name):
    """Clé de comparaison : sans parenthèses, sans accents, singulier approximatif."""
    return " ".join(w.rstrip("s") for w in strip_accents(base_of(name)).split())


def split_compound(ing):
    """« Thym, laurier, sel, poivre » → liste d'ingrédients, ou None si pas un composé connu."""
    name, qty, unit, cat = ing[:4]
    if "(" in name or cat != "spices" or "," not in name:
        return None
    parts = [p.strip().lower() for p in name.split(",")]
    if not all(p in COMPONENTS for p in parts):
        return None
    has_salt = any(p in SALTS for p in parts)
    out = []
    for i, p in enumerate(parts):
        label, fixed = COMPONENTS[p]
        keep = (p in SALTS) if has_salt else (i == 0)
        q, u = (qty, unit) if keep or fixed is None else fixed
        new_cat = "produce" if label == "Sauge fraîche" else "spices"
        out.append([label, q, u, new_cat] + list(ing[4:]))
    return out


def main():
    apply = "--apply" in sys.argv
    data = rs.load_recipes()
    items = data["items"]
    log = collections.Counter()

    # 1 + 2 : composés et synonymes
    for r in items:
        new_ing = []
        for ing in r["ing"]:
            parts = split_compound(ing)
            if parts:
                log[f"composé : {ing[0]} → {' + '.join(p[0] for p in parts)}"] += 1
                new_ing.extend(parts)
                continue
            if (ing[0], ing[2]) in NAME_UNIT_RENAMES:
                log[f"renommé : {ing[0]} ({ing[2]}) → {NAME_UNIT_RENAMES[(ing[0], ing[2])]}"] += 1
                ing = [NAME_UNIT_RENAMES[(ing[0], ing[2])]] + list(ing[1:])
            if ing[0] in INGREDIENT_RENAMES:
                log[f"renommé : {ing[0]} → {INGREDIENT_RENAMES[ing[0]]}"] += 1
                ing = [INGREDIENT_RENAMES[ing[0]]] + list(ing[1:])
            new_ing.append(ing)
        # Fusion dans la recette si un composant était déjà présent (même nom + unité)
        merged, seen = [], {}
        for ing in new_ing:
            k = (ing[0], ing[2], ing[3])
            if k in seen and len(ing) == 4 and len(seen[k]) == 4:
                seen[k][1] = seen[k][1] + ing[1]
                log[f"fusionné dans la recette : {ing[0]}"] += 1
                continue
            seen[k] = ing
            merged.append(ing)
        r["ing"] = merged

    # 3 : « frais » neutre
    base_keys = collections.defaultdict(set)  # rayon → clés présentes SANS « frais »
    for r in items:
        for ing in r["ing"]:
            if not FRAIS_RE.search(base_of(ing[0])):
                base_keys[ing[3]].add(key_of(ing[0]))
    for r in items:
        for ing in r["ing"]:
            if ing[3] not in ("produce", "meat-fish", "frozen", "pantry"):
                continue
            stripped = FRAIS_RE.sub("", ing[0]).strip()
            if stripped != ing[0] and key_of(stripped) in base_keys[ing[3]]:
                log[f"« frais » retiré : {ing[0]} → {stripped}"] += 1
                ing[0] = stripped

    # 4 : unités
    for r in items:
        for ing in r["ing"]:
            fix = UNIT_FIXES.get((ing[0], ing[2])) or UNIT_FIXES.get((base_of(ing[0]), ing[2]))
            if fix:
                f, u = fix
                q = round(f(ing[1]), 3)
                log[f"unité : {ing[0]} {ing[2]} → {u}"] += 1
                ing[1], ing[2] = q, u

    # 5 : rayon majoritaire par nom (sauf rayon imposé)
    CATEGORY_BY_BASE_KEYS = {key_of(k): v for k, v in CATEGORY_BY_BASE.items()}
    cats = collections.defaultdict(collections.Counter)
    for r in items:
        for ing in r["ing"]:
            cats[ing[0]][ing[3]] += 1
    for r in items:
        for ing in r["ing"]:
            best = (CATEGORY_OVERRIDES.get(ing[0]) or CATEGORY_BY_BASE_KEYS.get(key_of(ing[0]))
                    or cats[ing[0]].most_common(1)[0][0])
            if ing[3] != best:
                log[f"rayon : {ing[0]} {ing[3]} → {best}"] += 1
                ing[3] = best

    for k, v in sorted(log.items()):
        print(f"{v:4d}  {k}")
    print(f"\n{sum(log.values())} modification(s)")
    if apply:
        rs.save_recipes(data)
        print("✅ data/recipes.js écrit")


if __name__ == "__main__":
    main()
