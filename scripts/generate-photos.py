#!/usr/bin/env python3
"""generate-photos.py — pipeline DALL-E 3 batch pour photos catalogue.

Lit data-recipes, identifie les recettes sans `photo`, appelle DALL-E 3
via API OpenAI, télécharge PNG, convertit en WebP, sauvegarde dans
assets/recipes/<id>.webp, et patche data-recipes pour ajouter le field.

PRÉ-REQUIS :
  - OPENAI_API_KEY dans env
  - Bibliothèques : openai, requests, Pillow (pip install)
  - cwebp installé (dnf install libwebp-tools) — pour conversion WebP
    (fallback PIL si cwebp absent)

USAGE :
  python3 scripts/generate-photos.py --dry-run       # liste seulement
  python3 scripts/generate-photos.py --count 5       # génère 5 photos
  python3 scripts/generate-photos.py --cuisine indien --count 10
  python3 scripts/generate-photos.py --type lunch --count 20
  python3 scripts/generate-photos.py --ids l190,d201,d202
  python3 scripts/generate-photos.py --overwrite     # re-génère existantes

COÛT :
  ~0.04 €/photo (DALL-E 3 standard 1024x1024)
  50 photos = ~2 €
  600 photos = ~24 €

PRIVACY :
  La clé OPENAI_API_KEY reste dans l'env du terminal, jamais commitée.
  Photos uploadées dans assets/recipes/ (repo public), pas chez OpenAI.
"""

import os
import re
import sys
import json
import argparse
import subprocess
import datetime as dt
from pathlib import Path


def extract_recipes(index_path):
    with open(index_path, encoding="utf-8") as f:
        content = f.read()
    m = re.search(
        r'(<script type="application/json" id="data-recipes">\s*)(\{.*?\})(\s*</script>)',
        content, re.DOTALL)
    if not m:
        raise RuntimeError("data-recipes introuvable")
    return content, m, json.loads(m.group(2))


def filter_recipes(recipes, args, assets_dir):
    """Filtre les recettes selon args CLI."""
    items = recipes.get("items", [])

    # Filtre par ids explicites
    if args.ids:
        ids = [i.strip() for i in args.ids.split(",")]
        items = [r for r in items if r.get("id") in ids]

    # Filtre par cuisine
    if args.cuisine:
        items = [r for r in items if r.get("cuisine") == args.cuisine]

    # Filtre par type
    if args.type:
        items = [r for r in items if r.get("type") == args.type]

    # Exclure recettes déjà avec photo (sauf --overwrite)
    if not args.overwrite:
        items = [r for r in items if not r.get("photo")]
        # Et vérif fichier physique présent
        items = [r for r in items if not (assets_dir / f"{r['id']}.webp").exists()]

    # Limite count
    if args.count > 0:
        items = items[:args.count]

    return items


def build_prompt(recipe, config):
    """Construit le prompt DALL-E unifié pour une recette."""
    name = recipe.get("name", "?")
    cuisine = recipe.get("cuisine", "universel")
    base = config["base_style"]
    ratio = config["aspect_ratio_default"]
    modifier = config["per_cuisine_modifiers"].get(cuisine, "")
    negative = config.get("negative_prompts", "")
    return f"{name}, {base}, {ratio}{modifier}. {negative}"


def call_openai(prompt, api_key, settings):
    """Appel DALL-E 3 — retourne URL image générée."""
    try:
        from openai import OpenAI
    except ImportError:
        print("❌ Module openai non installé. pip install openai")
        sys.exit(2)

    client = OpenAI(api_key=api_key)
    response = client.images.generate(
        model=settings.get("model", "dall-e-3"),
        prompt=prompt,
        size=settings.get("size", "1024x1024"),
        quality=settings.get("quality", "standard"),
        n=1,
    )
    return response.data[0].url


def download_image(url, dest_png):
    """Télécharge l'image depuis l'URL temporaire DALL-E."""
    try:
        import requests
    except ImportError:
        print("❌ Module requests non installé. pip install requests")
        sys.exit(2)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    dest_png.write_bytes(resp.content)


def convert_to_webp(src_png, dest_webp, quality=82, width=1280, height=720):
    """Convertit PNG → WebP via cwebp (préféré) ou Pillow."""
    # Tentative cwebp
    if subprocess.run(["which", "cwebp"], capture_output=True).returncode == 0:
        cmd = ["cwebp", "-q", str(quality), "-resize", str(width), str(height),
               str(src_png), "-o", str(dest_webp)]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0:
            return True

    # Fallback Pillow
    try:
        from PIL import Image
    except ImportError:
        print("❌ Ni cwebp ni Pillow installés. dnf install libwebp-tools OR pip install Pillow")
        sys.exit(2)

    img = Image.open(src_png)
    # Resize en gardant l'aspect ratio puis crop center
    img.thumbnail((width * 2, height * 2), Image.LANCZOS)
    # Crop carré au centre
    w, h = img.size
    if w > h:
        left = (w - h) // 2
        img = img.crop((left, 0, left + h, h))
    else:
        top = (h - w) // 2
        img = img.crop((0, top, w, top + w))
    img = img.resize((1024, 1024), Image.LANCZOS)
    img.save(dest_webp, "WEBP", quality=quality)
    return True


def patch_recipe_photo(content, m, data, target_ids, photo_paths):
    """Met à jour data-recipes avec les nouveaux champs photo."""
    for r in data["items"]:
        if r["id"] in target_ids and r["id"] in photo_paths:
            r["photo"] = photo_paths[r["id"]]
    new_raw = json.dumps(data, ensure_ascii=False, indent=2)
    new_content = content[:m.start()] + m.group(1) + new_raw + m.group(3) + content[m.end():]
    return new_content


def main():
    parser = argparse.ArgumentParser(description="Génère les photos catalogue via DALL-E 3")
    parser.add_argument("--count", type=int, default=0,
                        help="nombre max de recettes à traiter (0 = toutes)")
    parser.add_argument("--cuisine", type=str, default=None,
                        help="filtre par cuisine")
    parser.add_argument("--type", type=str, default=None,
                        help="filtre par type")
    parser.add_argument("--ids", type=str, default=None,
                        help="liste d'ids séparés par virgule")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-génère même si photo existe")
    parser.add_argument("--dry-run", action="store_true",
                        help="liste seulement, ne génère pas")
    parser.add_argument("--no-patch", action="store_true",
                        help="ne pas patcher data-recipes (juste générer fichiers)")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    index_path = repo_root / "index.html"
    assets_dir = repo_root / "assets" / "recipes"
    prompts_path = Path(__file__).resolve().parent / "photo-prompts.json"

    if not index_path.exists():
        print(f"❌ {index_path} introuvable")
        sys.exit(2)
    if not prompts_path.exists():
        print(f"❌ {prompts_path} introuvable")
        sys.exit(2)

    # Vérif clé API
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not args.dry_run:
        print("❌ OPENAI_API_KEY non définie. export OPENAI_API_KEY='sk-...'")
        sys.exit(2)

    # Création dir assets
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Chargement config
    config = json.loads(prompts_path.read_text(encoding="utf-8"))

    # Chargement recettes
    content, m, data = extract_recipes(index_path)

    # Filtrage
    items = filter_recipes(data, args, assets_dir)

    if not items:
        print("⚠️ Aucune recette à traiter avec ces filtres.")
        return

    # Estimation coût
    cost_per = config["api_settings"].get("estimated_cost_eur", 0.04)
    total_cost = len(items) * cost_per
    print(f"Recettes à traiter : {len(items)}")
    print(f"Coût estimé      : {total_cost:.2f} €")
    print()

    if args.dry_run:
        for r in items:
            prompt = build_prompt(r, config)
            print(f"  {r['id']:6} {r['name'][:50]}")
            print(f"         prompt: {prompt[:100]}...")
        print(f"\n✅ Dry-run terminé. {len(items)} recettes seraient générées.")
        return

    # Confirmation
    confirm = input(f"Continuer ? [y/N] : ").strip().lower()
    if confirm != "y":
        print("Annulé.")
        return

    # Pipeline
    photo_paths = {}
    target_ids = set()
    tmp_dir = Path("/tmp/dalle-png")
    tmp_dir.mkdir(exist_ok=True)

    for i, r in enumerate(items, 1):
        rid = r["id"]
        print(f"\n[{i}/{len(items)}] {rid} {r['name'][:50]}")
        try:
            prompt = build_prompt(r, config)
            print(f"  Génération DALL-E...")
            url = call_openai(prompt, api_key, config["api_settings"])

            tmp_png = tmp_dir / f"{rid}.png"
            print(f"  Téléchargement PNG...")
            download_image(url, tmp_png)

            dest_webp = assets_dir / f"{rid}.webp"
            print(f"  Conversion WebP...")
            convert_to_webp(tmp_png, dest_webp, **config["webp_settings"])

            # Suppression PNG temp
            tmp_png.unlink(missing_ok=True)

            rel_path = f"assets/recipes/{rid}.webp"
            photo_paths[rid] = rel_path
            target_ids.add(rid)
            print(f"  ✅ {rel_path}")

        except KeyboardInterrupt:
            print("\n⚠️ Interrompu. Données partielles patchées si --no-patch absent.")
            break
        except Exception as e:
            print(f"  ❌ Échec : {e}")
            continue

    # Patch data-recipes
    if photo_paths and not args.no_patch:
        print(f"\nPatch data-recipes pour {len(photo_paths)} recettes...")
        new_content = patch_recipe_photo(content, m, data, target_ids, photo_paths)
        index_path.write_text(new_content, encoding="utf-8")
        print(f"✅ index.html mis à jour")

    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Photos générées : {len(photo_paths)}/{len(items)}")
    print(f"Coût réel estimé : {len(photo_paths) * cost_per:.2f} €")


if __name__ == "__main__":
    main()
