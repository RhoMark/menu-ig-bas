#!/usr/bin/env python3
"""lint-new-recipes.py — Pre-flight validator pour les nouveaux Lots de recettes.

Usage :
    python3 scripts/lint-new-recipes.py /tmp/lot65-recipes.py
    python3 scripts/lint-new-recipes.py /tmp/lot65-recipes.py --cell italien/breakfast
    python3 scripts/lint-new-recipes.py /tmp/lot65-recipes.py --varname LOT65

12 checks bloquants avant injection :
 1. Schéma JSON (champs obligatoires, types, vocabulary fermé)
 2. IDs uniques + format (b/l/d/s/des + numéro)
 3. Cellule cible respectée (cuisine × type)
 4. Dénominations qualifiées (V2.43.0+) — "Lait" seul interdit
 5. Allergens auto-déduits (saumon → fish obligatoire)
 6. Tags cohérents (vegan + viande = erreur)
 7. CG estimée par recette (bloque si > seuil mealType)
 8. Couverture data-glycemic (ingrédients hors base signalés)
 9. Macros minimales (≥80% ingrédients calculables)
10. rest/advance cohérents
11. Doublons (Jaccard sur ingrédients vs catalogue existant)
12. Saisonnalité (avertit si la saison à venir n'est pas couverte)

Exit code :
    0  → tout vert, injection autorisée
    1  → warnings seulement, injection à valider à la main
    2  → erreurs bloquantes, injection interdite
"""

import sys
import re
import json
import argparse
import datetime as dt
import unicodedata
from pathlib import Path
from importlib import util as importlib_util

# ────────────────────────── COULEURS CONSOLE ──────────────────────────
RESET = "\033[0m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"

# ────────────────────────── RÉFÉRENCE ──────────────────────────
VALID_TYPES = {"breakfast", "lunch", "dinner", "snack", "dessert"}
VALID_CUISINES = {"francais", "italien", "mediterraneen", "asiatique",
                  "indien", "mexicain", "maghrebin", "universel"}
VALID_SEASONS = {"spring", "summer", "autumn", "winter"}
VALID_DIFFICULTIES = {1, 2, 3}
# Doivent rester alignés avec validate-recipe-data.py (ALLOWED_EQUIPMENT / ALLOWED_ALLERGENS)
VALID_EQUIPMENT = {"stove", "oven", "blender", "bowl", "pan", "grill",
                   "cast-iron", "steamer", "pressure-cooker", "microwave"}
VALID_ALLERGENS = {"lactose", "gluten", "nuts", "eggs", "fish", "sesame",
                   "soy", "shellfish", "mustard", "egg"}

# V2.99.63 — Fractions hardcodées dans les steps (retour HedgeX 2026-05-26).
# Pattern bug : step dit « le demi-œuf battu » alors que la liste d'ingrédients
# scalée pour la famille affiche par ex. 2 œufs (cf. d99). La step ne suit pas
# le scaling. WARN level : peut aussi être un split intra-recette légitime
# (« la moitié pour la garniture, le reste pour la sauce ») → à juger à l'œil.
HARDCODED_FRACTION_NOUNS = (
    r"o?euf|œuf|citron|orange|pomme|tomate|oignon|tranche|gousse|carotte|"
    r"courgette|aubergine|poivron|concombre|avocat|mangue|melon|banane|"
    r"pasteque|pastèque|ananas|kiwi|ail|fenouil|navet|radis|panais"
)
HARDCODED_FRACTION_RE = re.compile(
    r"\b(?:demi[- ]|moitié\s+de\s+l[' ’]|½\s*|1/2\s+|¼\s*|1/4\s+|quart\s+(?:de|d[' ’]\s*))"
    r"(?:du?\s+|d[' ’]\s*)?"
    rf"({HARDCODED_FRACTION_NOUNS})s?\b",
    flags=re.IGNORECASE
)

# Champs obligatoires
REQUIRED_FIELDS = ["id", "name", "type", "cuisine", "seasons", "prep", "cook",
                   "diff", "cost", "kcal", "tags", "eq", "allergens", "ing", "steps"]

# Dénominations génériques interdites (V2.43.0+) si seules.
# Le regex matche "Lait" tout seul mais pas "Lait demi-écrémé".
GENERIC_NAMES_FORBIDDEN = {
    "lait": ["demi-écrémé", "demi-ecreme", "écrémé", "ecreme", "entier", "amande",
             "coco", "soja", "avoine", "riz", "noisette", "noix"],
    "riz": ["basmati", "long", "rond", "complet", "brun", "noir", "sauvage",
            "soufflé", "soufle", "gluant", "thaï", "thai"],
    "pâtes": ["complètes", "completes", "intégrales", "integrales", "sarrasin",
              "épeautre", "epeautre"],
    "pates": ["complètes", "completes", "intégrales", "integrales", "sarrasin",
              "épeautre", "epeautre"],
    "farine": ["t80", "t110", "t150", "pois chiche", "épeautre", "epeautre",
               "sarrasin", "amande", "coco", "complète", "complete", "maïs",
               "mais", "manioc", "riz", "mochiko", "châtaigne", "chataigne",
               "lentille", "millet"],
    "yaourt": ["nature", "grec", "brassé", "brasse", "brebis", "chèvre", "chevre",
               "végétal", "vegetal", "amande", "coco", "soja"],
    "beurre": ["doux", "demi-sel", "salé", "sale", "clarifié", "clarifie",
               "amande", "cacahuète", "cacahuete"],
    "pain": ["complet", "levain", "seigle", "pita", "naan", "tortilla",
             "blé entier", "ble entier", "intégral", "integral", "épeautre", "epeautre"],
    "sucre": ["roux", "complet", "coco", "muscovado", "rapadura"],
    "huile": ["olive", "colza", "sésame", "sesame", "coco", "noix", "tournesol",
              "argan", "lin", "avocat", "noisette"],
}

# Map ingrédient (keyword) → allergen obligatoire
ALLERGEN_TRIGGERS = {
    "fish": ["saumon", "thon", "sardine", "maquereau", "cabillaud", "morue",
             "lieu", "merlu", "haddock", "anchois", "hareng", "truite", "loup",
             "dorade", "rouget", "sole", "limande", "bar", "carrelet", "poisson"],
    "shellfish": ["crevette", "crabe", "homard", "langouste", "huître", "huitre",
                  "moule", "coquillage", "calamar", "calamars", "encornet", "poulpe",
                  "seiche", "noix de saint-jacques", "saint-jacques"],
    "eggs": ["œuf", "oeuf", "jaune d'œuf", "blanc d'œuf", "jaune d'oeuf", "blanc d'oeuf"],
    "lactose": ["lait", "yaourt", "fromage", "crème", "creme", "beurre", "mascarpone",
                "ricotta", "feta", "parmesan", "comté", "comte", "mozzarella", "burrata",
                "chèvre", "chevre", "brebis", "emmental", "gruyère", "gruyere",
                "cheddar", "manchego"],
    "gluten": ["farine", "pain", "pâtes", "pates", "boulgour", "couscous",
               "semoule", "soba", "épeautre", "epeautre", "seigle", "orge",
               "tortilla", "pita", "brick", "filo", "biscuit", "brioche",
               "baguette", "spaghetti", "tagliatelle", "lasagne", "penne"],
    "nuts": ["amande", "noix", "noisette", "pistache", "cajou", "pécan", "pecan",
             "macadamia", "praline"],
    "soy": ["soja", "tofu", "tempeh", "miso", "sauce soja", "edamame", "lait de soja"],
    "sesame": ["sésame", "sesame", "tahin", "tahini", "huile de sésame", "huile de sesame"],
    "mustard": ["moutarde"],
}

# Tags incompatibles
TAG_CONFLICTS = [
    # (tag1, allergens_qui_interdisent_tag1)
    ("vegan", ["fish", "shellfish", "eggs", "lactose"]),
    ("vegetarian", ["fish", "shellfish"]),
]

# Seuils CG par mealType (Harvard / GIF Sydney / CLAUDE.md)
CG_THRESHOLDS = {
    "breakfast": 9,   # 6-9
    "lunch":     14,  # 12-14 (sensibilité optimale midi)
    "dinner":    10,  # 8-10 (sensibilité réduite soir)
    "snack":     6,   # 4-6
    "dessert":   8,   # < 8
}

# Saison à venir selon date courante (HedgeX rule)
def upcoming_season(today=None):
    if today is None:
        today = dt.date.today()
    m = today.month
    # avril-juin → été ; juillet-septembre → automne ; octobre-décembre → hiver ; janvier-mars → printemps
    if m in (4, 5, 6): return "summer"
    if m in (7, 8, 9): return "autumn"
    if m in (10, 11, 12): return "winter"
    return "spring"

# ────────────────────────── HELPERS ──────────────────────────
def canonical(name):
    n = (name or "").strip().lower()
    n = n.replace('œ', 'oe').replace('æ', 'ae')
    n = ''.join(c for c in unicodedata.normalize('NFD', n) if unicodedata.category(c) != 'Mn')
    n = re.sub(r'\s*\([^)]*\)\s*', ' ', n)
    n = re.sub(r',.*$', '', n)
    n = re.sub(r'\ben poudre\b', ' ', n)
    n = re.sub(r'\bmoulu[es]?\b', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def lookup_glycemic(name, glyc_map):
    """Réplique la logique JS V2.99.18 (fallback étendu)."""
    c = canonical(name)
    if c in glyc_map: return glyc_map[c]
    # Strip prep
    PREP = re.compile(r'\b(rape|rapee|hache|hachee|emince|emincee|coupe|coupee|pele|pelee)\b')
    s = PREP.sub('', c).strip()
    if s and s in glyc_map: return glyc_map[s]
    # Strip qualifiers
    QUAL = re.compile(r'\s+(complet|complete|vert|verte|rouge|rouges|jaune|rose|mur|mure|frais|fraiche|sec|seche|leger|legere|doux|douce|ferme|nature|denoyaute|denoyautee|grille|grillee|cuit|cuite|fume|fumee)$')
    nq = QUAL.sub('', s).strip()
    nq = QUAL.sub('', nq).strip()
    if nq and nq in glyc_map: return glyc_map[nq]
    if nq and nq.endswith('s') and len(nq) > 3 and nq[:-1] in glyc_map: return glyc_map[nq[:-1]]
    # Pluriel naïf
    if s.endswith('s') and len(s) > 3 and s[:-1] in glyc_map: return glyc_map[s[:-1]]
    return None

NEGLIGIBLE_NUTRI = [
    "glacon", "eau", "eau de rose", "eau de fleur d'oranger", "eau froide",
    "eau bouillante", "eau chaude", "eau tiede", "feuille de laurier", "laurier",
    "herbes de provence", "bouquet garni", "clou de girofle", "girofle",
    "piment d'espelette", "piment doux", "piment vert", "piment rouge", "piment",
    "petale", "fleur", "colorant", "extrait", "vanille", "vanille en gousse",
    "gousse de vanille", "feuille de gelatine", "gelatine", "agar-agar",
    "bicarbonate de sodium", "bicarbonate", "sel", "fleur de sel", "sel fin",
    "sel noir kala namak", "poivre", "poivre noir", "poivre blanc",
]
def is_negligible(canon_name):
    if canon_name in NEGLIGIBLE_NUTRI: return True
    return any(k in canon_name for k in NEGLIGIBLE_NUTRI if len(k) >= 5)

def load_lot(path, varname):
    """Charge dynamiquement le fichier Python contenant LOTxx."""
    p = Path(path).resolve()
    if not p.exists():
        print(f"{RED}❌ Fichier introuvable : {p}{RESET}")
        sys.exit(2)
    spec = importlib_util.spec_from_file_location("lot_module", p)
    mod = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, varname):
        # Auto-detect une variable commençant par LOT
        candidates = [k for k in dir(mod) if k.startswith("LOT") and isinstance(getattr(mod, k), list)]
        if candidates:
            varname = candidates[0]
            print(f"{DIM}  ↳ variable auto-détectée : {varname}{RESET}")
        else:
            print(f"{RED}❌ Variable {varname} introuvable dans {p}{RESET}")
            sys.exit(2)
    return getattr(mod, varname)

def load_existing_data(repo_root):
    index = Path(repo_root) / "index.html"
    content = index.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="data-recipes">\s*(\{.*?\})\s*</script>', content, re.DOTALL)
    recipes = json.loads(m.group(1))["items"]
    m = re.search(r'<script type="application/json" id="data-glycemic">\s*(\{.*?\})\s*</script>', content, re.DOTALL)
    glyc = json.loads(m.group(1))["items"]
    glyc_map = {canonical(it["id"]): it for it in glyc}
    return recipes, glyc_map

def jaccard(a, b):
    if not a or not b: return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb)

# ────────────────────────── CHECKS ──────────────────────────
class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []

    def err(self, rid, msg):
        self.errors.append((rid, msg))
    def warn(self, rid, msg):
        self.warnings.append((rid, msg))
    def info(self, rid, msg):
        self.infos.append((rid, msg))

def check_schema(recipe, report):
    rid = recipe.get("id", "?")
    for f in REQUIRED_FIELDS:
        if f not in recipe:
            report.err(rid, f"champ obligatoire manquant : `{f}`")
    if recipe.get("type") not in VALID_TYPES:
        report.err(rid, f"type invalide : {recipe.get('type')!r} (attendu : {VALID_TYPES})")
    if recipe.get("cuisine") not in VALID_CUISINES:
        report.err(rid, f"cuisine invalide : {recipe.get('cuisine')!r}")
    if recipe.get("diff") not in VALID_DIFFICULTIES:
        report.err(rid, f"diff doit être 1, 2 ou 3 (reçu {recipe.get('diff')!r})")
    seasons = recipe.get("seasons", [])
    if not isinstance(seasons, list) or not all(s in VALID_SEASONS for s in seasons):
        report.err(rid, f"seasons invalide : {seasons!r}")
    for e in recipe.get("eq", []):
        if e not in VALID_EQUIPMENT:
            report.err(rid, f"eq invalide : {e!r} (attendu parmi {sorted(VALID_EQUIPMENT)})")
    for a in recipe.get("allergens", []):
        if a not in VALID_ALLERGENS:
            report.err(rid, f"allergen invalide : {a!r} (attendu parmi {sorted(VALID_ALLERGENS)})")
    if recipe.get("prep", 0) + recipe.get("cook", 0) <= 0:
        report.err(rid, f"prep+cook doit être > 0")
    ing = recipe.get("ing", [])
    if len(ing) < 2:
        report.err(rid, f"ing < 2 (au moins 2 ingrédients requis)")
    steps = recipe.get("steps", [])
    if len(steps) < 2:
        report.err(rid, f"steps < 2 (au moins 2 étapes requises)")
    elif len(steps) < 3:
        report.warn(rid, f"steps court : {len(steps)} (style ado-cuisine recommande ≥3)")

def check_ids_format(recipes, existing_recipes, report):
    valid_prefix = re.compile(r'^(b|l|d|s|des)\d+$')
    new_ids = set()
    existing_ids = {r["id"] for r in existing_recipes}
    for r in recipes:
        rid = r.get("id", "?")
        if not valid_prefix.match(rid):
            report.err(rid, f"id format invalide (attendu b/l/d/s/des + nombre)")
        if rid in existing_ids:
            report.err(rid, f"id déjà utilisé dans le catalogue")
        if rid in new_ids:
            report.err(rid, f"id en doublon dans ce Lot")
        new_ids.add(rid)

def check_cell(recipes, cell_arg, report):
    if not cell_arg:
        return
    try:
        target_cuisine, target_type = cell_arg.split("/")
    except ValueError:
        print(f"{YELLOW}⚠️ --cell mal formaté (attendu : cuisine/type){RESET}")
        return
    for r in recipes:
        if r.get("cuisine") != target_cuisine or r.get("type") != target_type:
            report.warn(r.get("id", "?"),
                       f"hors cellule cible {target_cuisine}/{target_type} "
                       f"({r.get('cuisine')}/{r.get('type')})")

def check_generic_names(recipes, report):
    for r in recipes:
        rid = r.get("id", "?")
        for ing_entry in r.get("ing", []):
            if not ing_entry: continue
            name = ing_entry[0].lower().strip()
            first = re.split(r'[\s,()]', name, maxsplit=1)[0]
            if first in GENERIC_NAMES_FORBIDDEN:
                qualifiers = GENERIC_NAMES_FORBIDDEN[first]
                if not any(q in name for q in qualifiers):
                    report.err(rid, f"dénomination générique interdite : '{ing_entry[0]}' "
                                    f"(qualifier requis parmi : {qualifiers[:3]}...)")

def check_allergens_consistency(recipes, report):
    # V2.99.19 — Détection allergens fine, ingrédient par ingrédient (pas
    # concat global) pour éviter les faux positifs ("lait de coco" ≠ lactose).
    NON_LACTOSE_MILKS = re.compile(r"\blait\s+(de\s+|d')?(coco|amande|soja|avoine|riz|noisette|noix|chanvre|epeautre|épeautre)\b")
    # "Semoule/farine de maïs/riz/sarrasin" = sans gluten malgré le mot semoule/farine
    GLUTEN_FREE_FLOURS = re.compile(r'\b(semoule|farine|pâtes?|pates?)\s+(de\s+|d\')?(ma[iï]s|riz|sarrasin|pois\s+chiche|chataigne|châtaigne|coco|amande|manioc|tapioca|millet|teff|quinoa|sorgho|mochiko|lentille)\b')
    # "Riz gluant" : le nom contient "gluant" mais c'est juste sticky, pas gluten
    STICKY_RICE = re.compile(r'\briz\s+gluant\b')

    for r in recipes:
        rid = r.get("id", "?")
        declared = set(r.get("allergens", []))
        detected = {}  # allergen → liste ingredients qui l'ont déclenché

        for ing_entry in r.get("ing", []):
            if not ing_entry: continue
            ing_name = ing_entry[0].lower()
            ing_canon = canonical(ing_entry[0])

            for allergen, keywords in ALLERGEN_TRIGGERS.items():
                for kw in keywords:
                    if re.search(r'\b' + re.escape(kw) + r'\b', ing_name):
                        # Exceptions fines
                        if allergen == "lactose" and NON_LACTOSE_MILKS.search(ing_name):
                            continue  # lait végétal, pas lactose
                        if allergen == "gluten":
                            if GLUTEN_FREE_FLOURS.search(ing_name):
                                continue  # semoule/farine de maïs/riz/sarrasin = sans gluten
                            if STICKY_RICE.search(ing_name):
                                continue  # "riz gluant" = sticky, pas gluten
                        if allergen == "shellfish" and kw == "moule" and "moule" not in ing_name.split():
                            continue  # éviter de matcher "moelleux"
                        detected.setdefault(allergen, []).append(ing_entry[0])
                        break

        for allergen, triggers in detected.items():
            if allergen not in declared:
                example = triggers[0]
                report.err(rid, f"allergen manquant : `{allergen}` (déclenché par '{example}')")

def check_tags_consistency(recipes, report):
    for r in recipes:
        rid = r.get("id", "?")
        tags = set(r.get("tags", []))
        allergens = set(r.get("allergens", []))
        for tag, forbidden_allergens in TAG_CONFLICTS:
            if tag in tags:
                conflicts = set(forbidden_allergens) & allergens
                if conflicts:
                    report.err(rid, f"tag `{tag}` incompatible avec allergens : {conflicts}")
        # quick + (prep+cook)>30
        if "quick" in tags and (r.get("prep", 0) + r.get("cook", 0)) > 30:
            report.err(rid, f"tag `quick` mais prep+cook = {r.get('prep',0)+r.get('cook',0)} min (>30)")
        # festif sans contexte ado-friendly = warning
        if "festif" in tags and "kid-friendly" in tags:
            # OK
            pass

def check_cg_threshold(recipes, glyc_map, report):
    for r in recipes:
        rid = r.get("id", "?")
        mealType = r.get("type")
        if mealType not in CG_THRESHOLDS:
            continue
        threshold = CG_THRESHOLDS[mealType]
        # Calculer CG estimée
        total_cg = 0
        for ing in r.get("ing", []):
            if not ing or len(ing) < 3: continue
            name, qty, unit = ing[0], ing[1], ing[2]
            entry = lookup_glycemic(name, glyc_map)
            if not entry or entry.get("ig") is None: continue
            # Approx : qty en g (sera plus précis avec qtyToGrams)
            if unit.lower() in ("g", "gramme"):
                grams = qty
            elif unit.lower() in ("ml", "centilitre"):
                grams = qty  # approx pour les liquides
            else:
                continue  # skip si on ne sait pas convertir
            carbs = entry.get("carbsPer100g") or 0
            ig = entry.get("ig") or 0
            cg_ing = (grams * carbs / 100) * ig / 100
            total_cg += cg_ing
        # Par portion (4 portions par défaut)
        cg_per_portion = total_cg / 4
        # V2.99.19 — CG estimée approximative (qtyToGrams JS plus précis).
        # On warn dès dépassement, on bloque seulement si >2× seuil (probable
        # vraie sortie de seuil même avec marge d'incertitude). Empêche le
        # blocage abusif sur des recettes correctes mais où le calcul Python
        # surestime la CG par manque de granularité unités.
        if cg_per_portion > threshold * 2.0:
            report.err(rid, f"CG estimée {cg_per_portion:.1f} ≫ seuil {mealType} ({threshold}) — à vérifier")
        elif cg_per_portion > threshold:
            report.warn(rid, f"CG estimée {cg_per_portion:.1f} > seuil {mealType} ({threshold})")

def check_glycemic_coverage(recipes, glyc_map, report, all_missing):
    for r in recipes:
        rid = r.get("id", "?")
        countable = 0
        covered = 0
        missing_in_recipe = []
        for ing in r.get("ing", []):
            if not ing: continue
            c = canonical(ing[0])
            if is_negligible(c): continue
            countable += 1
            if lookup_glycemic(ing[0], glyc_map):
                covered += 1
            else:
                missing_in_recipe.append(ing[0])
                all_missing[c] = all_missing.get(c, 0) + 1
        if countable == 0: continue
        ratio = covered / countable
        if ratio < 0.5:
            report.err(rid, f"couverture nutri {ratio:.0%} ({covered}/{countable}). "
                            f"Manquants : {missing_in_recipe[:3]}...")
        elif ratio < 0.8:
            report.warn(rid, f"couverture nutri {ratio:.0%} ({covered}/{countable}). "
                             f"Manquants : {missing_in_recipe[:3]}...")

def check_rest_advance(recipes, report):
    for r in recipes:
        rid = r.get("id", "?")
        rest = r.get("rest")
        if rest is not None and rest >= 120 and not r.get("advance"):
            report.err(rid, f"rest={rest} min ≥120 mais champ `advance` manquant")

# V2.99.x — Unités d'ingrédients pièges (retour HedgeX 2026-06-03).
# Certains ingrédients ont un `weightPerPiece` = pièce vendue (tête, botte) alors
# que la recette en utilise une sous-unité. Ex : "Ail" en "u" = 1 tête (100 g) →
# une recette affichait 400 g d'ail. La bonne unité est "gousse" (≈4 g).
FORBIDDEN_INGREDIENT_UNITS = {
    "Ail": ({"u"}, "gousse"),   # ail : jamais en tête, toujours en gousse
}
def check_ingredient_units(recipes, report):
    for r in recipes:
        rid = r.get("id", "?")
        for ing in r.get("ing", []):
            if not isinstance(ing, list) or len(ing) < 3:
                continue
            name, unit = ing[0], ing[2]
            rule = FORBIDDEN_INGREDIENT_UNITS.get(name)
            if rule and unit in rule[0]:
                report.err(rid, f"« {name} » mesuré en \"{unit}\" interdit "
                                f"(pièce vendue, surdosage) → utiliser \"{rule[1]}\"")

def check_doublons(recipes, existing_recipes, report):
    for r in recipes:
        rid = r.get("id", "?")
        name_lower = r.get("name", "").lower()
        new_ing = {canonical(i[0]) for i in r.get("ing", []) if i}
        for existing in existing_recipes:
            if existing.get("cuisine") != r.get("cuisine"): continue
            if existing.get("type") != r.get("type"): continue
            ex_ing = {canonical(i[0]) for i in existing.get("ing", []) if i}
            j = jaccard(new_ing, ex_ing)
            ex_name = existing.get("name", "").lower()
            if j > 0.7:
                report.warn(rid, f"doublon potentiel avec '{existing['name']}' "
                                 f"({existing['id']}, Jaccard {j:.0%})")
                break
            # Match approximatif sur le nom
            if name_lower and ex_name and len(name_lower) > 10:
                common = sum(1 for w in name_lower.split() if w in ex_name and len(w) > 3)
                if common >= 3:
                    report.warn(rid, f"nom proche : '{existing['name']}' ({existing['id']})")
                    break

def check_seasonality(recipes, report):
    upcoming = upcoming_season()
    for r in recipes:
        rid = r.get("id", "?")
        seasons = r.get("seasons", [])
        if upcoming not in seasons and seasons != list(VALID_SEASONS) and len(seasons) < 4:
            report.info(rid, f"seasons ne contient pas la saison à venir ({upcoming}). "
                             f"Vérifier intention.")

def check_step_hardcoded_fractions(recipes, report):
    """V2.99.63 — Détecte 'demi-œuf' / 'moitié de l'oignon' / '½ tranche'
    dans les steps : chiffres bruts de la recette de base qui ne suivent
    pas le scaling famille (cf. d99 « le demi-œuf battu » alors que la liste
    affiche par ex. 2 œufs). WARN, pas erreur : peut être un split intra-
    recette légitime (à juger à l'œil)."""
    for r in recipes:
        rid = r.get("id", "?")
        for i, step in enumerate(r.get("steps", []) or [], 1):
            for m in HARDCODED_FRACTION_RE.finditer(step):
                noun = m.group(1).lower()
                report.warn(rid,
                    f"step {i} : « {m.group(0)} » — fraction hardcodée. "
                    f"Préfère « le/les {noun} » (référence à la liste scalée). "
                    f"Si c'est un split intra-recette légitime, ignore.")
                break  # un seul flag par step pour éviter le bruit

# ────────────────────────── PRINT REPORT ──────────────────────────
def print_report(report, lot, all_missing):
    print(f"\n{BOLD}━━━ Rapport lint pour {len(lot)} recettes ━━━{RESET}")

    if report.errors:
        print(f"\n{RED}{BOLD}❌ ERREURS BLOQUANTES ({len(report.errors)}){RESET}")
        for rid, msg in report.errors:
            print(f"  {RED}● {rid:6}{RESET} {msg}")
    if report.warnings:
        print(f"\n{YELLOW}{BOLD}⚠️  WARNINGS ({len(report.warnings)}){RESET}")
        for rid, msg in report.warnings:
            print(f"  {YELLOW}● {rid:6}{RESET} {msg}")
    if report.infos:
        print(f"\n{BLUE}ℹ️  INFOS ({len(report.infos)}){RESET}")
        for rid, msg in report.infos:
            print(f"  {BLUE}● {rid:6}{RESET} {msg}")

    if all_missing:
        print(f"\n{CYAN}{BOLD}📋 INGRÉDIENTS À AJOUTER À data-glycemic ({len(all_missing)}){RESET}")
        for name, count in sorted(all_missing.items(), key=lambda x: -x[1])[:15]:
            print(f"  {CYAN}●{RESET} {count:2}× {name}")
        if len(all_missing) > 15:
            print(f"  {DIM}... et {len(all_missing) - 15} autres{RESET}")
        print(f"\n  {DIM}→ Lance : python3 scripts/auto-enrich-glycemic.py /tmp/lotXX.py{RESET}")

    print(f"\n{BOLD}━━━ VERDICT ━━━{RESET}")
    if report.errors:
        print(f"{RED}{BOLD}❌ INJECTION BLOQUÉE — {len(report.errors)} erreurs à corriger{RESET}\n")
        return 2
    elif report.warnings or all_missing:
        print(f"{YELLOW}{BOLD}⚠️  INJECTION POSSIBLE MAIS VÉRIFIER WARNINGS{RESET}\n")
        return 1
    else:
        print(f"{GREEN}{BOLD}✅ TOUT VERT — INJECTION AUTORISÉE{RESET}\n")
        return 0

# ────────────────────────── MAIN ──────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Lint pre-flight pour nouveaux Lots de recettes")
    parser.add_argument("file", help="Fichier Python avec LOTxx (ex: /tmp/lot65-recipes.py)")
    parser.add_argument("--varname", default="LOT", help="Nom de la variable LOT (auto-détecté si non précisé)")
    parser.add_argument("--cell", default=None, help="Cellule cible : cuisine/type (ex: italien/breakfast)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    print(f"{BOLD}📋 lint-new-recipes.py — pre-flight check{RESET}")
    print(f"  fichier : {args.file}")
    if args.cell:
        print(f"  cellule cible : {args.cell}")
    print()

    lot = load_lot(args.file, args.varname)
    print(f"  ↳ {len(lot)} recettes chargées")

    existing_recipes, glyc_map = load_existing_data(repo_root)
    print(f"  ↳ catalogue existant : {len(existing_recipes)} recettes, {len(glyc_map)} ingrédients data-glycemic")

    report = Report()
    all_missing = {}

    # 12 checks
    for r in lot:
        check_schema(r, report)
    check_ids_format(lot, existing_recipes, report)
    check_cell(lot, args.cell, report)
    check_generic_names(lot, report)
    check_allergens_consistency(lot, report)
    check_tags_consistency(lot, report)
    check_cg_threshold(lot, glyc_map, report)
    check_glycemic_coverage(lot, glyc_map, report, all_missing)
    check_rest_advance(lot, report)
    check_ingredient_units(lot, report)
    check_doublons(lot, existing_recipes, report)
    check_seasonality(lot, report)
    check_step_hardcoded_fractions(lot, report)

    exit_code = print_report(report, lot, all_missing)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
