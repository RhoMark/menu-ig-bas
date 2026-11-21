#!/usr/bin/env python3
"""V2.144.0 — Vérifie que chaque emoji présent dans l'appli (index.html,
data/recipes.js) a son icône dans la police « App Icons » (unicode-range de
tailwind-input.css). Un emoji absent s'afficherait en emoji couleur au milieu
des icônes au trait.

Corriger : ajouter l'emoji dans MAP de scripts/build-icon-font.py, relancer
ce script de construction (voir son en-tête), puis rebuild Tailwind.

Usage : python3 scripts/audit-emoji-icons.py   (code retour 1 si manque)
"""
import re
import sys

css = open("tailwind-input.css", encoding="utf-8").read()
m = re.search(r'font-family: "App Icons";.*?unicode-range: ([^;]*);', css, re.S)
if not m:
    sys.exit("unicode-range App Icons introuvable dans tailwind-input.css")
covered = {int(x.strip()[2:], 16) for x in m.group(1).split(",")}

# Pictogrammes « emoji » (hors flèches/coches typographiques gardées en texte).
EMO = re.compile(r"[\U0001F000-\U0001FAFF☀-➿⬅-⭕⌚-⏿ℹ↗↘]")
TEXT_OK = set("✓✕✗★☆☐▶▲▼●")
missing = {}
for path in ("index.html", "data/recipes.js"):
    for i, line in enumerate(open(path, encoding="utf-8"), 1):
        if "\ufe0f" in line:
            # Le sélecteur U+FE0F force l'emoji couleur : à retirer.
            missing.setdefault("\ufe0f", []).append(f"{path}:{i}")
        for ch in EMO.findall(line):
            if ch in TEXT_OK or ord(ch) in covered:
                continue
            missing.setdefault(ch, []).append(f"{path}:{i}")
# V2.147.1 — L'URL de la police porte son empreinte (?h=) : sans elle, un ancien
# service worker resservait l'ancienne police (ex. 🦐 affiché en poisson).
import hashlib
h = hashlib.md5(open("vendor/fonts/app-icons.woff2", "rb").read()).hexdigest()[:8]
for path in ("tailwind-input.css", "sw.js"):
    if f"app-icons.woff2?h={h}" not in open(path, encoding="utf-8").read():
        print(f"❌ {path} : mettre l'URL de la police à app-icons.woff2?h={h}")
        sys.exit(1)
if missing:
    for ch, where in sorted(missing.items()):
        print(f"❌ {ch} (U+{ord(ch):X}) sans icône — {', '.join(where[:3])}{' …' if len(where) > 3 else ''}")
    sys.exit(1)
print("✅ Emojis : tous ont leur icône au trait.")
