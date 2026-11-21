#!/usr/bin/env python3
"""vocab.py — SOURCE UNIQUE des vocabulaires fermés de recettes.

Importé par `lint-new-recipes.py` ET `validate-recipe-data.py` pour qu'ils
ne puissent JAMAIS diverger. C'est la cause racine du bug allergène réparé
en V2.99.76 : les deux scripts tenaient chacun une copie codée en dur de la
liste d'allergènes, qui avait dérivé de `data-allergens` (le vocab UI) en y
laissant traîner `egg` (mauvais id, le bon est `eggs`) et `mustard` (absent
de l'UI) → 14 recettes mal taggées non exclues pour un allergique aux œufs.

Deux familles de vocabulaire :

  1. DÉRIVÉS de index.html (l'UI EST la source de vérité). Parsés depuis les
     blocs `data-*`. Ajouter un allergène / une catégorie / une cuisine dans
     index.html suffit : les scripts le prennent automatiquement, zéro édition
     Python. Garantie : ces trois vocabulaires sont, à l'instant T, identiques
     dans l'UI, dans les recettes et dans les validateurs (vérifié V2.99.78).

  2. PROPRES À L'AUTHORING (pas de bloc UI, ou volontairement distincts de
     l'UI). Définis ici, une seule fois.

Divergences eq / tags VOLONTAIRES — ne PAS « corriger » en dérivant de l'UI :
  - `eq` : les recettes utilisent `pan` (que l'UI n'expose pas comme filtre) ;
    l'UI expose `wok` / `bbq` / `air-fryer` / `stand-mixer` / `multi-cooker`
    que les recettes n'emploient pas (un wok se code `stove`, cf. leçon #7).
    Le vocabulaire d'authoring n'est donc PAS la liste de filtres UI.
  - `tags` : les recettes portent `festif` / `light` / `apero-sec` /
    `apero-dinatoire` / `epicerie-specialisee`, absents de `data-tags` (qui
    ne liste que les 6 chips de filtre primaires de l'UI).
"""

import re
import json
import collections
from functools import lru_cache
from pathlib import Path

INDEX_DEFAULT = Path(__file__).resolve().parent.parent / "index.html"


@lru_cache(maxsize=None)
def _block_ids(block_id, index_path):
    """Renvoie le frozenset des `id` d'un bloc <script id="data-..."> de index.html."""
    path = Path(index_path) if index_path else INDEX_DEFAULT
    html = path.read_text(encoding="utf-8")
    m = re.search(
        r'<script[^>]*id="%s"[^>]*>\s*(.*?)\s*</script>' % re.escape(block_id),
        html, re.DOTALL)
    if not m:
        raise RuntimeError(f"Bloc {block_id!r} introuvable dans {path}")
    return frozenset(item["id"] for item in json.loads(m.group(1))["items"])


# ── 1. Dérivés de index.html (UI = source de vérité) ──────────────────────

def allergens(index_path=None):
    """9 allergènes du bloc data-allergens (gluten, lactose, eggs, …, mustard)."""
    return _block_ids("data-allergens", index_path)


def categories(index_path=None):
    """Catégories d'ingrédient (produce, pantry, dairy, …) du bloc data-categories."""
    return _block_ids("data-categories", index_path)


def cuisines(index_path=None):
    """8 cuisines du bloc data-cuisines (francais, italien, …, universel)."""
    return _block_ids("data-cuisines", index_path)


# ── 2. Vocabulaire d'authoring (défini une seule fois) ────────────────────

# V2.140.0 — Un article = un nom (liste de courses). Nom interdit → nom à
# utiliser. Appliqué une fois par normalize-ingredient-names.py, puis bloquant
# dans validate-recipe-data.py et lint-new-recipes.py (le synonyme ne revient pas).
INGREDIENT_RENAMES = {
    # Crèmes : 4 produits du rayon frais
    "Crème fraîche liquide": "Crème liquide légère",
    "Crème liquide légère 15%": "Crème liquide légère",
    "Crème fraîche légère": "Crème liquide légère",
    "Crème fraîche allégée": "Crème fraîche épaisse légère",
    "Crème fraîche épaisse 15%": "Crème fraîche épaisse légère",
    "Crème fraîche": "Crème fraîche épaisse légère",
    # Herbes
    "Persil frais": "Persil plat",
    "Persil plat frais": "Persil plat",
    "Persil plat frais (ciselé)": "Persil plat (ciselé)",
    # Épices entières ≠ moulues (canonicalName retire « moulu » / « en poudre »)
    "Bâton de cannelle": "Cannelle en bâton",
    "Cannelle (bâton)": "Cannelle en bâton",
    "Cannelle bâton": "Cannelle en bâton",
    "Cardamome": "Cardamome en gousses",
    "Cardamome (gousse)": "Cardamome en gousses",
    "Cardamome verte": "Cardamome en gousses",
    "Cardamome verte (gousses)": "Cardamome en gousses",
    "Clou de girofle moulu": "Girofle moulu",
    "Vanille (extrait)": "Extrait de vanille",
    "Vanille (extrait, ou gousse)": "Extrait de vanille",
    "Vanille (extrait, si pas de pandan)": "Extrait de vanille",
    "Vanille (gousse, ou extrait)": "Gousse de vanille",
    "Vanille": "Vanille en poudre",
    "Vanille en gousse": "Vanille en poudre",
    "Poivre": "Poivre noir",
    "Poivre du moulin": "Poivre noir",
    "Poivre noir du moulin": "Poivre noir",
    "Poivre noir moulu": "Poivre noir",
    "Sel fin": "Sel",
    "Laurier": "Feuille de laurier",
    "Noix de muscade": "Muscade",
    "Muscade râpée": "Muscade",
    "Thym": "Thym séché",
    "Origan": "Origan séché",
    # Même article, autre libellé
    "Bouillon de bœuf (cube)": "Cube de bouillon de bœuf",
    "Bouillon de poulet (cube)": "Cube de bouillon de poulet",
    "Feuille de gélatine (2 g/feuille)": "Feuille de gélatine",
    "Feuille de gélatine (2 g)": "Feuille de gélatine",
    "Feuilles de nori": "Feuille de nori",
    "Feuille de nori (algue grillée)": "Feuille de nori",
    "Feuille de curry (facultatif)": "Feuilles de curry",
    "Feuilles de curry (facultatif)": "Feuilles de curry",
    "Piment doux (jalapeño)": "Piment jalapeño",
    "Piment doux (facultatif)": "Piment doux frais",
    "Piment doux (épépiné, émincé)": "Piment doux frais",
    "Sardines fraîches vidées": "Sardines fraîches",
    "Petits oignons grelots": "Oignons grelots",
    "Petit pois": "Petits pois",
    "Petits pois frais": "Petits pois",
    "Petits pois frais (ou surgelés)": "Petits pois (frais ou surgelés)",
    "Petits pois frais ou surgelés": "Petits pois (frais ou surgelés)",
    "Petites pâtes complètes": "Pâtes complètes (petites)",
    "Anchois (facultatif)": "Anchois à l'huile (facultatif)",
    "Lait demi-écrémé tiède": "Lait demi-écrémé (tiède)",
    # V2.140.3 — En français courant « citron » = citron jaune ; on précise seulement
    # les autres (citron vert, zeste de citron…). Demande HedgeX 2026-11-21.
    "Citron jaune": "Citron",
    "Oignon jaune": "Oignon",   # idem : « oignon » = oignon jaune ; on précise rouge, blanc, nouveau
    "Citron jaune (jus)": "Citron (jus)",
    "Citron jaune (zeste)": "Citron (zeste)",
    "Citron jaune (zeste + jus)": "Citron (zeste + jus)",
    "Citron jaune (bio si possible, on utilise le zeste)": "Citron (bio si possible, on utilise le zeste)",
    # V2.140.4 — Même produit, libellés différents (« en boîte », ordre des mots…). Retour HedgeX
    # (Tomates concassées / Tomates concassées en boîte), puis revue de tout le catalogue.
    "Tomates concassées en boîte": "Tomates concassées",
    "Tomates pelées en boîte": "Tomates pelées",
    "Haricots blancs en bocal": "Haricots blancs cuits",
    "Haricots blancs en conserve": "Haricots blancs cuits",
    "Pois chiches en bocal": "Pois chiches cuits",
    "Pois chiches en conserve": "Pois chiches cuits",
    "Thon au naturel égoutté": "Thon au naturel (égoutté)",
    "Thon en boîte (au naturel)": "Thon au naturel",
    "Thon en boîte au naturel": "Thon au naturel",
    "Thon en boîte au naturel (égoutté)": "Thon au naturel (égoutté)",
    "Thon naturel (en boîte)": "Thon au naturel",
    "Thon naturel en boîte": "Thon au naturel",
    "Tomatillo (en conserve, égouttés)": "Tomatillos en bocal (égouttés)",
    "Tomatillos en boîte": "Tomatillos en bocal",
    "Tomatillos en bocal (= salsa verde maison rapide)": "Tomatillos en bocal",
    "Tomatillos (ou tomates vertes en bocal)": "Tomatillos en bocal (ou tomates vertes)",
    "Cacahuète non salée grillée": "Cacahuètes grillées non salées",
    "Cacahuète non salée grillée (facultatif)": "Cacahuètes grillées non salées (facultatif)",
    "Datte Medjool": "Dattes Medjool",
    "Datte medjool": "Dattes Medjool",
    "Datte Medjool dénoyautée (facultatif)": "Dattes Medjool dénoyautées (facultatif)",
    "Dattes medjool dénoyautées": "Dattes Medjool dénoyautées",
    "Falafel cuit (ou tofu mariné si pas de falafel)": "Falafels (ou tofu mariné)",
    "Gélatine en feuille": "Feuille de gélatine",
    "Fruits rouges mélangés (frais ou surgelés)": "Fruits rouges (frais ou surgelés)",
    "Mélange fruits rouges": "Fruits rouges",
    "Mélange fruits rouges (frais ou surgelés)": "Fruits rouges (frais ou surgelés)",
    "Mélange fruits rouges (fraises, framboises, myrtilles)": "Fruits rouges (fraises, framboises, myrtilles)",
    "Fruits rouges congelés": "Fruits rouges surgelés",
    "Gambas décortiquées crues": "Gambas crues décortiquées",
    "Crevettes décortiquées crues": "Crevettes crues décortiquées",
    "Crevettes décortiquées cuites": "Crevettes cuites décortiquées",
    "Crevettes décortiquées (cuites)": "Crevettes cuites décortiquées",
    "Haricots verts frais (ou surgelés)": "Haricots verts (frais ou surgelés)",
    "Haricots verts frais ou surgelés": "Haricots verts (frais ou surgelés)",
    "Mangue (fraîche ou surgelée décongelée)": "Mangue (fraîche ou surgelée)",
    "Mangue surgelée ou fraîche": "Mangue (fraîche ou surgelée)",
    "Mangue surgelée en cubes": "Mangue surgelée",
    "Mangue mûre (surgelée)": "Mangue surgelée",
    "Maïs en grains (frais ou surgelés)": "Maïs en grains (frais ou surgelé)",
    "Maïs en grains (ou surgelé)": "Maïs en grains (frais ou surgelé)",
    "Pâte miso": "Pâte de miso",
    "Pâtes courtes complètes (ditali ou coquillettes)": "Pâtes complètes courtes (ditali ou coquillettes)",
    "Pesto": "Pesto au basilic",
    "Pesto basilic": "Pesto au basilic",
    "Pesto vert": "Pesto au basilic",
    "Pesto vert (basilic-pignons)": "Pesto au basilic",
    "Piments guajillo séchés": "Piment guajillo séché",
    "Piments séchés (guajillo)": "Piment guajillo séché",
    "Riz complet rond": "Riz rond complet",
    "Sauce poisson (nuoc mam)": "Sauce de poisson (nuoc-mâm)",
    "Sauce poisson (nuoc-mam)": "Sauce de poisson (nuoc-mâm)",
    "Tortilla maïs": "Tortilla de maïs",
    "Tortilla maïs complète": "Tortilla de maïs complète",
    "Tortilla maïs (chips de tortilla complète)": "Tortilla de maïs (chips de tortilla complète)",
    "Pain complet de seigle": "Pain de seigle complet",
    # V2.140.5 — Fruits et légumes : même article, libellés différents (revue du rayon frais).
    "Poireaux": "Poireau",
    "Brocolis": "Brocoli",
    "Pruneau dénoyauté": "Pruneaux",
    "Fraise fraîche bien mûre": "Fraises (bien mûres)",
    "Salade roquette": "Roquette",
    "Salade mâche (ou roquette)": "Mâche (ou roquette)",
    "Betterave rouge cuite": "Betterave cuite",
    "Betteraves cuites sous vide": "Betterave cuite",
    "Champignons (Paris ou mélangés)": "Champignons de Paris (ou mélangés)",
    "Mange-tout (pois gourmands)": "Pois gourmands",
    "Pois mange-tout": "Pois gourmands",
    "Fèves fraîches écossées": "Fèves fraîches (écossées)",
    "Butternut": "Courge butternut",
    "Pousses de soja": "Germes de soja",
    "Pousses de soja (haricot mungo)": "Germes de soja",
    "Feuilles de menthe fraîche": "Menthe fraîche",
    "Feuilles de basilic thaï": "Basilic thaï",
    "Aubergine moyenne": "Aubergine",
    "Courgette tendre": "Courgette",
    "Fenouil bulbe": "Fenouil",
    "Épinards frais ou surgelés": "Épinards frais (ou surgelés)",
    "Salade verte pour accompagner": "Salade verte",
    # V2.140.6 — Revue des articles rangés dans « Divers » (Épicerie, Crèmerie, Épices, Boucherie…).
    "Bicarbonate de sodium": "Bicarbonate de soude",
    "Bouillon de poulet": "Bouillon de volaille",
    "Bouillon de légumes chaud": "Bouillon de légumes",
    "Bouillon": "Bouillon de légumes",
    "Cacahuètes nature": "Cacahuètes non salées",
    "Cacahuètes grillées non salées": "Cacahuètes non salées",
    "Cacahuètes grillées non salées (facultatif)": "Cacahuètes non salées (facultatif)",
    "Châtaignes cuites sous vide": "Châtaignes cuites",
    "Eau bouillante": "Eau",
    "Eau chaude (80 °C)": "Eau",
    "Eau froide": "Eau",
    "Eau glacée": "Eau",
    "Eau tiède": "Eau",
    "Frik (blé vert concassé)": "Freekeh",
    "Lait de coco cuisine": "Lait de coco",
    "Linguini complets": "Linguine complètes",
    "Maïs doux en grains (boîte, égoutté)": "Maïs doux (boîte, égoutté)",
    "Maïs en grains (boîte sans sucre)": "Maïs doux (boîte, sans sucre ajouté)",
    "Maïzena": "Fécule de maïs (Maïzena)",
    "Fécule de maïs": "Fécule de maïs (Maïzena)",
    "Olives noires Kalamata": "Olives Kalamata",
    "Olives noires Kalamata dénoyautées": "Olives Kalamata (dénoyautées)",
    "Olives noires dénoyautées": "Olives noires (dénoyautées)",
    "Olive verte": "Olives vertes",
    "Olives vertes dénoyautées": "Olives vertes (dénoyautées)",
    "Tamarin (pâte)": "Pâte de tamarin",
    "Pois cassés secs": "Pois cassés",
    "Sachet de thé vert (genmaicha, sencha ou jasmin)": "Thé vert (genmaicha, sencha ou jasmin)",
    "Vin rouge sec": "Vin rouge",
    "Badiane": "Anis étoilé",
    "5 épices chinoises (ou mélange cannelle-anis-girofle)": "Cinq-épices (ou mélange cannelle-anis-girofle)",
    "Fenouil (graines)": "Graines de fenouil",
    "Biscuit cuillère": "Biscuits cuillère",
    "Biscuit cuillère (boudoir)": "Biscuits cuillère (boudoirs)",
    "Biscuits cuillère (boudoir) ou speculoos": "Biscuits cuillère (ou speculoos)",
    "Boudoirs (ou biscuits cuiller)": "Biscuits cuillère (boudoirs)",
    "Épaule d'agneau désossée": "Épaule d'agneau (désossée)",
    "Épaule d'agneau en cubes": "Épaule d'agneau (en cubes)",
    "Tranche de gigot d'agneau": "Gigot d'agneau (tranche)",
    "Gigot d'agneau (tranche ou portion)": "Gigot d'agneau (tranche)",
    "Filet de daurade royale": "Filet de daurade",
    "Filet de daurade extra-frais (qualité ceviche)": "Filet de daurade (extra-frais, qualité ceviche)",
    "Saint-Jacques décoquillées": "Noix de Saint-Jacques",
    "Framboises fraîches ou surgelées": "Framboises (fraîches ou surgelées)",
    "Épaule d'agneau désossée, coupée en cubes": "Épaule d'agneau (désossée, en cubes)",
    "Viande hachée d'agneau": "Agneau haché",
    "Pruneaux dénoyautés": "Pruneaux (dénoyautés)",
    "Boulghour": "Boulgour",
    "Olive noire dénoyautée": "Olives noires (dénoyautées)",
    "Olive verte dénoyautée": "Olives vertes (dénoyautées)",
    "Sauce nuoc-mâm": "Sauce de poisson (nuoc-mâm)",
    "Amande non salée": "Amandes entières",
    "Amande entière non salée": "Amandes entières",
    "Amandes en poudre": "Poudre d'amande",
    "Noix décortiquées": "Cerneaux de noix",
    "Noix de Grenoble": "Cerneaux de noix",
    "Noix concassée": "Cerneaux de noix concassés",
    "Pistache non salée hachée": "Pistaches non salées (hachées)",
    "Pistache hachée": "Pistaches non salées (hachées)",
    "Pistaches décortiquées non salées": "Pistaches non salées",
    "Graines de sésame blanc": "Graines de sésame",
    "Sésame grillé": "Graines de sésame grillées",
    "Sucre glace pour la déco": "Sucre glace",
    "Sarrasin en grains": "Sarrasin",
    "Semoule fine de blé complet": "Semoule complète fine",
    "Semoule de blé complète (fine)": "Semoule complète fine",
    "Riz noir Venere (ou riz brun)": "Riz noir (Venere) ou riz brun",
    "Polenta (semoule de maïs)": "Polenta",
    "Ghee (beurre clarifié)": "Beurre clarifié (ghee)",
    "Beurre clarifié": "Beurre clarifié (ghee)",
    "Ghee (beurre clarifié) ou huile neutre": "Beurre clarifié (ghee) ou huile neutre",
    "Beurre doux pour le moule": "Beurre doux",
    "Encornets (calamars)": "Calamars",
    "Calmar, coupé en anneaux": "Calamars",
    "Filet de dorade": "Filet de daurade",
    "Lieu noir (filet)": "Filet de lieu noir",
    "Merlu (filet)": "Filet de merlu",
    "Saumon frais (qualité sushi)": "Filet de saumon (qualité sushi)",
    "Saumon frais qualité sashimi": "Filet de saumon (qualité sushi)",
    "Bœuf haché 5% MG": "Bœuf haché 5%",
    "Viande hachée de bœuf (5 % MG)": "Bœuf haché 5%",
    "Graines de cumin entières": "Graines de cumin",
    "Feuilles de curry séchées (facultatif)": "Feuilles de curry (facultatif)",
    "Fromage frais nature": "Fromage frais",
    "Yaourt grec nature": "Yaourt grec",
    "Parmesan râpé en copeaux": "Parmesan en copeaux",
    "Feta émiettée": "Feta",
    "Jambon blanc tranche": "Jambon blanc",
    "Pita complet": "Pain pita complet",
    "Pita complète": "Pain pita complet",
    "Pain pita complet pour servir": "Pain pita complet",
    "Zeste de citron jaune": "Zeste de citron",
    "Fleur d'oranger": "Eau de fleur d'oranger",
    "Fleur d'oranger (eau)": "Eau de fleur d'oranger",
    "Tomatillo": "Tomatille",
    "Tomatillos (ou tomate verte)": "Tomatille (ou tomate verte)",
}

# Composés interdits : un ingrédient par ligne (« Sel, poivre » → Sel + Poivre noir).
COMPOUND_SPICES_RE = r"^(sel|fleur de sel|poivre|muscade|thym|laurier|romarin|cumin|origan séché|basilic séché|sauge fraîche)(\s*,\s*(sel|fleur de sel|poivre|muscade|thym|laurier|romarin|cumin|origan séché|basilic séché|sauge fraîche))+$"

TYPES = frozenset({"breakfast", "lunch", "dinner", "snack", "dessert"})

# Saisons concrètes (pour les heuristiques de couverture saisonnière) ;
# SEASONS y ajoute "all" (recette toutes saisons), accepté à la validation.
SEASONS_CONCRETE = frozenset({"spring", "summer", "autumn", "winter"})
SEASONS = SEASONS_CONCRETE | {"all"}

DIFFICULTIES = frozenset({1, 2, 3})

TAGS = frozenset({"vegetarian", "vegan", "batch-friendly", "quick", "no-cook",
                  "kid-friendly", "festif", "light", "apero-sec",
                  "apero-dinatoire", "epicerie-specialisee"})

EQUIPMENT = frozenset({"stove", "oven", "blender", "bowl", "pan", "grill",
                       "cast-iron", "steamer", "pressure-cooker", "microwave"})


# ── Conteneur résolu (sets dérivés figés pour un index.html donné) ────────

Vocab = collections.namedtuple(
    "Vocab",
    "types seasons seasons_concrete difficulties tags equipment "
    "allergens categories cuisines")


def load(index_path=None):
    """Résout tous les vocabulaires pour un index.html donné (defaut : repo)."""
    return Vocab(
        types=TYPES,
        seasons=SEASONS,
        seasons_concrete=SEASONS_CONCRETE,
        difficulties=DIFFICULTIES,
        tags=TAGS,
        equipment=EQUIPMENT,
        allergens=allergens(index_path),
        categories=categories(index_path),
        cuisines=cuisines(index_path),
    )
