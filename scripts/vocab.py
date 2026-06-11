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
