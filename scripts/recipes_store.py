"""recipes_store.py — Lecture / écriture du catalogue de recettes.

Depuis V2.115.0 le catalogue n'est plus dans index.html (qui approchait la
limite de 5 Mo) mais dans `data/recipes.js`, chargé par un <script> classique
AVANT l'app : la variable globale reste disponible au démarrage, sans attente.

Format du fichier (une seule ligne d'en-tête, puis du JSON indenté) :

    window.__DATA_RECIPES = {
      "schema": 1,
      "items": [...]
    };

Tous les scripts passent par ce module : un seul endroit à changer si le
format évolue.
"""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RECIPES_PATH = REPO / "data" / "recipes.js"
PREFIX = "window.__DATA_RECIPES = "
SUFFIX = ";\n"


def recipes_path_for(index_path):
    """Catalogue situé à côté d'un index.html donné (option --index des scripts)."""
    return Path(index_path).resolve().parent / "data" / "recipes.js"


def load_recipes(path=RECIPES_PATH):
    """Retourne le dict complet {"schema": …, "items": [...]}."""
    text = Path(path).read_text(encoding="utf-8")
    start = text.find(PREFIX)
    end = text.rstrip().rfind(";")
    if start < 0 or end < 0:
        raise RuntimeError(f"Format inattendu dans {path} (attendu : {PREFIX}{{…}};)")
    return json.loads(text[start + len(PREFIX):end])


def load_items(path=RECIPES_PATH):
    return load_recipes(path).get("items", [])


def dump_recipes(data):
    return PREFIX + json.dumps(data, ensure_ascii=False, indent=2) + SUFFIX


def save_recipes(data, path=RECIPES_PATH):
    Path(path).write_text(dump_recipes(data), encoding="utf-8")
