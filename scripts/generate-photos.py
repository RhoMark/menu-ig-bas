#!/usr/bin/env python3
"""generate-photos.py — photos du catalogue générées EN LOCAL (refonte 1D, V2.120.0).

Remplace l'ancienne version DALL·E (OpenAI, payante). Tout tourne sur le
mini-PC : aucun compte, aucune clé API, rien ne sort de la maison.

  Modèle   : FLUX.2 [klein] 4B (Black Forest Labs, Allemagne — licence Apache 2.0)
  Moteur   : stable-diffusion.cpp (MIT), binaire officiel Vulkan
  Matériel : ~38 s / photo sur la Radeon 890M
  Dossier  : ~/ia-photos (bin-vulkan/, models/, out/) — hors du repo
             (surchargeable par la variable MIJOTERIE_IA_DIR)

ÉTAPES :
  1. Générer (reprend là où ça s'est arrêté : les photos déjà faites sont sautées)
       python3 scripts/generate-photos.py --count 100
     → assets/recipes/<id>.webp (1024×576, ~45 Ko) + tâches/galerie-photos.html
  2. Relire la galerie ; refaire une photo ratée avec une autre graine :
       python3 scripts/generate-photos.py --ids d434,l12 --overwrite --seed 11
  3. Publier : ajoute le champ `photo` aux recettes dont la photo existe
       python3 scripts/generate-photos.py --apply

Ordre de priorité (sans --ids) : déjeuners et dîners de la saison en cours,
en alternant les cuisines, puis les desserts, puis le reste du catalogue.
Avec --frequence fichier.json ({id: nombre d'apparitions}, issu d'une
simulation de menus) : les recettes qui reviennent le plus passent d'abord.

Mention « Image générée par IA » affichée sur chaque photo (EU AI Act art. 50).
"""

import argparse
import datetime as dt
import html
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from recipes_store import load_recipes, save_recipes  # catalogue data/recipes.js

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets" / "recipes"
GALLERY = REPO / "tâches" / "galerie-photos.html"
CONFIG = Path(__file__).resolve().parent / "photo-prompts.json"
IA = Path(os.environ.get("MIJOTERIE_IA_DIR", Path.home() / "ia-photos"))


def current_season(today=None):
    m = (today or dt.date.today()).month
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
            6: "summer", 7: "summer", 8: "summer"}.get(m, "autumn")


def priority_order(items, season):
    """Déjeuners/dîners de saison (cuisines alternées), puis desserts de saison, puis le reste."""
    def round_robin(rs):
        by = defaultdict(list)
        for r in rs:
            by[r["cuisine"]].append(r)
        out, i = [], 0
        while any(by.values()):
            for c in sorted(by):
                if i < len(by[c]):
                    out.append(by[c][i])
            i += 1
            if all(i >= len(v) for v in by.values()):
                break
        return out
    in_season = lambda r: season in r.get("seasons", []) or "all" in r.get("seasons", [])
    first = round_robin([r for r in items if r["type"] in ("lunch", "dinner") and in_season(r)])
    second = round_robin([r for r in items if r["type"] == "dessert" and in_season(r)])
    seen = {r["id"] for r in first + second}
    return first + second + [r for r in items if r["id"] not in seen]


def main_ingredients(recipe, n=5):
    """Ingrédients visibles dans l'assiette : on écarte épices, huiles, sel, bouillons."""
    skip = ("sel", "poivre", "huile", "bouillon", "eau", "vinaigre", "levure", "extrait", "sauce soja")
    out = []
    for name, *_rest in recipe["ing"]:
        cat = _rest[2] if len(_rest) > 2 else ""
        base = name.split("(")[0].strip()
        if cat == "spices" or base.lower().startswith(skip):
            continue
        out.append(base)
        if len(out) >= n:
            break
    return out


def build_prompt(recipe, cfg):
    ing = ", ".join(main_ingredients(recipe))
    override = cfg.get("overrides", {}).get(recipe["id"])
    if override:  # nom trompeur pour le modèle (ex. « sandwich » → pain) : description explicite
        return f"Photo culinaire. {override}. " + cfg["per_type"].get(recipe["type"], "") + cfg["base_style"]
    return (f"Photo culinaire : {recipe['name']}. "
            + (f"Ingrédients visibles : {ing}. " if ing else "")
            + cfg["per_type"].get(recipe["type"], "") + cfg["base_style"])


def generate(recipe, cfg, seed, png):
    cmd = [str(IA / "bin-vulkan/sd-cli"),
           "--diffusion-model", str(IA / "models/flux-2-klein-4b-Q8_0.gguf"),
           "--vae", str(IA / "models/flux2-vae.safetensors"),
           "--llm", str(IA / "models/Qwen3-4B-Q8_0.gguf"),
           "-p", build_prompt(recipe, cfg),
           "--cfg-scale", "1.0", "--steps", "4", "--sampling-method", "euler",
           "-W", str(cfg["width"]), "-H", str(cfg["height"]), "-s", str(seed),
           "--vae-tiling", "-o", str(png)]
    env = dict(os.environ, LD_LIBRARY_PATH=str(IA / "bin-vulkan"))
    with open(str(png) + ".log", "w") as log:
        rc = subprocess.run(cmd, cwd=IA / "bin-vulkan", env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    return rc == 0 and png.exists()


def to_webp(png, webp, quality):
    from PIL import Image
    with Image.open(png) as im:
        im.convert("RGB").save(webp, "WEBP", quality=quality, method=6)


def write_gallery(items):
    """Galerie de relecture (privée, tâches/) : photos présentes, avec id pour demander une reprise."""
    by_id = {r["id"]: r for r in items}
    files = sorted(ASSETS.glob("*.webp"), key=lambda p: p.stat().st_mtime, reverse=True)
    cards = []
    for f in files:
        r = by_id.get(f.stem)
        if not r:
            continue
        cards.append(f'<figure><img src="../assets/recipes/{f.name}" loading="lazy" alt="">'
                     f'<figcaption><b>{html.escape(r["id"])}</b> · {html.escape(r["cuisine"])} · {html.escape(r["type"])}'
                     f'<br>{html.escape(r["name"])}</figcaption></figure>')
    GALLERY.write_text(
        '<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Galerie photos</title><style>body{font-family:system-ui;margin:16px;background:#f6f1e8;color:#2b2722}'
        '.g{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}figure{margin:0;background:#fffcf7;'
        'border:1px solid #ddd2c1;border-radius:12px;overflow:hidden}img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block}'
        'figcaption{padding:8px 10px;font-size:13px;line-height:1.35}</style></head><body>'
        f'<h1>Photos générées : {len(cards)}</h1><p>Plus récentes en premier. Pour refaire une photo : donner son identifiant '
        '(ex. <b>d434</b>).</p><div class="g">' + "".join(cards) + "</div></body></html>", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Photos du catalogue générées en local (FLUX.2 klein)")
    ap.add_argument("--count", type=int, default=0, help="nombre de photos à générer (0 = aucune limite)")
    ap.add_argument("--ids", type=str, default=None, help="identifiants séparés par des virgules")
    ap.add_argument("--overwrite", action="store_true", help="refaire même si la photo existe")
    ap.add_argument("--seed", type=int, default=7, help="graine (changer pour une autre version)")
    ap.add_argument("--season", type=str, default=None, help="saison prioritaire (défaut : saison en cours)")
    ap.add_argument("--frequence", type=str, default=None,
                    help="JSON {id: apparitions} : les recettes les plus fréquentes passent d'abord")
    ap.add_argument("--dry-run", action="store_true", help="affiche la liste et un exemple de consigne, sans générer")
    ap.add_argument("--apply", action="store_true", help="ajoute le champ photo aux recettes dont la photo existe")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    data = load_recipes()
    items = data["items"]
    ASSETS.mkdir(parents=True, exist_ok=True)

    if args.apply:
        n = 0
        for r in items:
            f = ASSETS / f"{r['id']}.webp"
            if f.exists() and r.get("photo") != f"assets/recipes/{f.name}":
                r["photo"] = f"assets/recipes/{f.name}"
                n += 1
        save_recipes(data)
        print(f"✅ champ photo ajouté à {n} recette(s) ({sum(1 for r in items if r.get('photo'))} au total)")
        return

    if args.ids:
        wanted = [i.strip() for i in args.ids.split(",") if i.strip()]
        by_id = {r["id"]: r for r in items}
        missing = [i for i in wanted if i not in by_id]
        if missing:
            sys.exit(f"❌ identifiants inconnus : {missing}")
        todo = [by_id[i] for i in wanted]
    else:
        todo = priority_order(items, args.season or current_season())
        if args.frequence:
            freq = json.loads(Path(args.frequence).read_text(encoding="utf-8"))
            rank = {r["id"]: k for k, r in enumerate(todo)}
            todo.sort(key=lambda r: (-freq.get(r["id"], 0), rank[r["id"]]))
    if not args.overwrite:
        todo = [r for r in todo if not (ASSETS / f"{r['id']}.webp").exists()]
    if args.count:
        todo = todo[:args.count]

    print(f"📸 {len(todo)} photo(s) à générer (~{len(todo) * 40 // 60} min)")
    if args.dry_run:
        for r in todo[:15]:
            print(f"   {r['id']:7} {r['cuisine']:13} {r['type']:9} {r['name'][:60]}")
        if todo:
            print("\nExemple de consigne :\n" + build_prompt(todo[0], cfg))
        return
    if not (IA / "bin-vulkan/sd-cli").exists():
        sys.exit(f"❌ moteur introuvable : {IA / 'bin-vulkan/sd-cli'}")

    out = IA / "out/catalogue"
    out.mkdir(parents=True, exist_ok=True)
    t0, done, failed = time.time(), 0, []
    for k, r in enumerate(todo, 1):
        png = out / f"{r['id']}-s{args.seed}.png"
        t = time.time()
        if generate(r, cfg, args.seed, png):
            to_webp(png, ASSETS / f"{r['id']}.webp", cfg["webp_quality"])
            done += 1
            write_gallery(items)
            print(f"[{k}/{len(todo)}] ✅ {r['id']} ({time.time() - t:.0f} s) {r['name'][:55]}", flush=True)
        else:
            failed.append(r["id"])
            print(f"[{k}/{len(todo)}] ❌ {r['id']} — voir {png}.log", flush=True)
    print(f"━━━ {done} photo(s) en {(time.time() - t0) / 60:.0f} min ; échecs : {failed or 'aucun'}")
    print("→ relire tâches/galerie-photos.html, puis : python3 scripts/generate-photos.py --apply")


if __name__ == "__main__":
    main()
