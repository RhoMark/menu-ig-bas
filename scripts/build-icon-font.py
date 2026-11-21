"""Construit vendor/fonts/app-icons.woff2 : police d'icônes Lucide (ISC) dont les
glyphes sont rangés SUR les codepoints des emojis utilisés par l'appli.
Résultat : chaque emoji s'affiche en icône au trait, couleur du texte (V2.144.0).

Reconstruire (après ajout d'un emoji dans MAP) :
  npm pack lucide-static@1.77.0 && tar xzf lucide-static-1.77.0.tgz   # -> package/
  python3 -m venv .venv && .venv/bin/pip install fonttools brotli
  .venv/bin/python scripts/build-icon-font.py package vendor/fonts/app-icons.woff2 /tmp/range.txt
  puis recopier /tmp/range.txt dans unicode-range (tailwind-input.css) et rebuild Tailwind.
  Mettre à jour l'empreinte ?h= de l'URL (tailwind-input.css + sw.js) : l'audit la donne.
Contrôle : python3 scripts/audit-emoji-icons.py"""
import json, sys
from fontTools.ttLib import TTFont
from fontTools import subset

LUCIDE = sys.argv[1]   # dossier package/ de lucide-static
OUT = sys.argv[2]      # chemin .woff2
CSS_OUT = sys.argv[3]  # fichier texte : unicode-range

# emoji -> candidats Lucide (le premier qui existe gagne)
MAP = {
    "⚠": ["triangle-alert", "alert-triangle"], "🍾": ["party-popper"], "🎉": ["party-popper"],
    "🌙": ["moon"], "🖨": ["printer"], "📄": ["file-text"], "⭐": ["star"], "🥗": ["salad"],
    "🍱": ["container", "package"], "✅": ["circle-check", "check-circle"], "⏱": ["timer"],
    "❤": ["heart"], "🎲": ["dices", "dice-5"], "🍰": ["cake-slice"], "🔒": ["lock"],
    "🔢": ["rectangle-ellipsis", "hash"], "💰": ["wallet"], "☀": ["sun"],
    "📊": ["chart-column", "bar-chart-3"], "🍽": ["utensils"], "🛒": ["shopping-cart"],
    "🥂": ["wine"], "🏆": ["trophy"], "⏳": ["hourglass"], "🩺": ["stethoscope"],
    "👥": ["users"], "🚫": ["ban"], "🌃": ["door-open"], "🍪": ["cookie"], "🌍": ["globe"],
    "🔀": ["shuffle"], "🔋": ["battery-charging"], "🗓": ["calendar-days"], "📅": ["calendar"],
    "✨": ["sparkles"], "🗑": ["trash-2"], "🌿": ["leaf"], "💚": ["heart"], "↗": ["trending-up"],
    "↘": ["trending-down"], "❄": ["snowflake"], "📖": ["book-open"], "📔": ["notebook"],
    "📱": ["smartphone"], "💡": ["lightbulb"], "☁": ["cloud"], "🥬": ["carrot"], "🥩": ["beef"],
    "♻": ["recycle"], "🏃": ["activity"], "📋": ["clipboard-list"], "🔓": ["lock-open", "unlock"],
    "🔥": ["flame"], "⏰": ["alarm-clock"], "🔄": ["refresh-cw"], "🥚": ["egg"], "🏷": ["tag"],
    "✍": ["pen-line"], "🐟": ["fish"], "💾": ["save"], "🏠": ["house", "home"],
    "📈": ["chart-line", "line-chart"], "💪": ["biceps-flexed", "dumbbell"], "⚡": ["zap"],
    "🧂": ["salt", "shaker", "flask-round"], "⛺": ["tent"], "🎾": ["volleyball"], "🏋": ["dumbbell"],
    "🥊": ["swords"], "💧": ["droplet"], "🥓": ["ham"], "🐠": ["fish-symbol", "fish"],
    "🫘": ["bean"], "🌓": ["sun-moon"], "ℹ": ["info"], "👤": ["user"], "🔗": ["link"],
    "❓": ["circle-help", "help-circle"], "⚙": ["settings"], "🔍": ["search"],
    "🧺": ["shopping-basket"], "🍳": ["chef-hat"], "🔁": ["repeat"], "💶": ["euro"],
    "🥑": ["droplets"], "🌾": ["wheat"], "🎯": ["target"], "🧹": ["brush-cleaning", "eraser"],
    "🎓": ["graduation-cap"], "🫙": ["package"], "🍞": ["croissant"], "🥖": ["croissant"], "🧊": ["snowflake"],
    "🍎": ["apple"], "🔣": ["type"], "💻": ["laptop"], "📸": ["camera"], "🫒": ["leaf"],
    "🥢": ["utensils"], "🍛": ["soup"], "🌮": ["sandwich"], "🥘": ["cooking-pot"], "🧑": ["user"],
    "🧒": ["user-round"], "👶": ["baby"], "🍼": ["milk"], "📜": ["scroll-text"],
    "📲": ["smartphone-nfc", "smartphone"], "📴": ["phone-off"], "🔑": ["key-round", "key"],
    "📷": ["camera"], "📂": ["folder-open"], "👪": ["users"], "🆕": ["badge-plus", "plus"],
    "📥": ["download"], "👋": ["hand"], "🚀": ["rocket"], "✏": ["pencil"], "🥕": ["carrot"],
    "🔝": ["arrow-up-to-line"], "📝": ["notebook-pen"], "🍬": ["candy"], "📚": ["library"],
    "🍴": ["utensils"], "📦": ["package"], "👑": ["crown"], "🛡": ["shield"], "⬇": ["arrow-down"],
    "⬆": ["arrow-up"], "🔐": ["lock-keyhole"], "🌱": ["sprout"], "👍": ["thumbs-up"],
    "👎": ["thumbs-down"], "🎂": ["cake"], "🍲": ["soup"], "🥣": ["soup"], "🥛": ["milk"],
    "🧀": ["cookie"], "🍝": ["utensils"], "🍕": ["pizza"], "🍷": ["wine"], "☕": ["coffee"],
    "🫖": ["coffee"], "📌": ["pin"], "🔔": ["bell"], "📧": ["mail"], "✉": ["mail"], "🧾": ["receipt"],
    "🗂": ["folder"], "📁": ["folder"], "🔎": ["search"], "🧪": ["flask-conical"], "🧭": ["compass"],
    "🌡": ["thermometer"], "⭕": ["circle"], "❌": ["circle-x"], "❗": ["circle-alert"], "🎁": ["gift"],
    "🍋": ["citrus"], "🍓": ["cherry"], "🍌": ["banana"], "🍇": ["grape"], "🥜": ["nut"],
    "🌶": ["flame"], "🧄": ["leaf"], "🧅": ["leaf"], "🍅": ["apple"], "🥦": ["leaf"], "🍄": ["leaf"],
    "🐔": ["drumstick"], "🍗": ["drumstick"], "🦐": ["shrimp", "fish"], "🦑": ["fish"], "🐄": ["beef"],
    "🏡": ["house"], "📍": ["map-pin"], "🗺": ["map"], "⌛": ["hourglass"], "🕐": ["clock"],
    "⏲": ["timer"], "🌊": ["waves"], "🌞": ["sun"], "🍂": ["leaf"], "🌸": ["flower"], "🌼": ["flower"],
    "🧘": ["activity"], "🚴": ["bike"], "🏊": ["waves"], "⚖": ["scale"], "🤖": ["bot"],
    "🌰": ["tree-deciduous", "nut"], "🐚": ["shell"], "🫛": ["bean"], "🫓": ["circle-ellipsis"],
    "🌭": ["flask-round"], "🥒": ["leafy-green", "leaf"], "🪻": ["flower-2", "flower"],
    "🎛": ["heater"], "📟": ["microwave"], "🧃": ["blender", "blend"], "🧁": ["cupcake", "cake"],
    "🍖": ["egg-fried"], "🪵": ["flame-kindling", "flame"], "🥡": ["soup"], "🎚": ["gauge"],
    "🔌": ["plug-zap"], "🌀": ["fan", "wind"],
    "👨": ["user"], "👩": ["user"], "👧": ["user-round"], "👦": ["user-round"],
}

nodes = json.load(open(f"{LUCIDE}/font/codepoints.json"))  # nom -> codepoint
font = TTFont(f"{LUCIDE}/font/lucide.ttf")
cmap = font.getBestCmap()
chosen, missing = {}, []
for emo, cands in MAP.items():
    for name in cands:
        if name in nodes and nodes[name] in cmap:
            chosen[emo] = cmap[nodes[name]]
            break
    else:
        missing.append((emo, cands))
if missing:
    print("MISSING", missing)

# Nouveau cmap : emoji -> glyphe Lucide ; FE0F / 200D -> glyphe vide (largeur 0).
for tag in ("GSUB", "GPOS", "GDEF"):
    if tag in font:
        del font[tag]
glyph_order = font.getGlyphOrder()
# Centrer les icônes sur la ligne de texte : descendre de 150 unités
# (boîte Lucide 84..916 -> -66..766, centre ~ mi-hauteur des capitales).
SHIFT = -150
gtab = font["glyf"]
for gname in glyph_order:
    gl = gtab[gname]
    if gl.numberOfContours > 0:
        coords = gl.coordinates
        coords.translate((0, SHIFT))
        gl.recalcBounds(gtab)
for tbl, a, d in ((font["hhea"], "ascent", "descent"), (font["OS/2"], "sTypoAscender", "sTypoDescender")):
    setattr(tbl, a, 880); setattr(tbl, d, -120)
font["OS/2"].usWinAscent, font["OS/2"].usWinDescent = 880, 120
font["OS/2"].sTypoLineGap = 0; font["hhea"].lineGap = 0
newmap = {}
for emo, g in chosen.items():
    newmap[ord(emo)] = g
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
t4 = CmapSubtable.newSubtable(4); t4.platformID, t4.platEncID, t4.language = 3, 1, 0
t12 = CmapSubtable.newSubtable(12); t12.platformID, t12.platEncID, t12.language = 3, 10, 0
t4.cmap = {c: g for c, g in newmap.items() if c <= 0xFFFF}
t12.cmap = dict(newmap)
font["cmap"].tables = [t4, t12]
# glyphe vide de largeur nulle pour les sélecteurs
from fontTools.pens.ttGlyphPen import TTGlyphPen
pen = TTGlyphPen(None)
order = list(glyph_order) + ["zwsel"]
font.setGlyphOrder(order)
font["glyf"].glyphOrder = order
font["glyf"].glyphs["zwsel"] = pen.glyph()
font["hmtx"].metrics["zwsel"] = (0, 0)
for sub in font["cmap"].tables:
    sub.cmap[0xFE0F] = "zwsel"
    sub.cmap[0x200D] = "zwsel"
# Nom de la police
for rec in font["name"].names:
    if rec.nameID in (1, 4, 6, 16):
        rec.string = "App Icons" if rec.nameID != 6 else "AppIcons"
font.save(OUT + ".ttf")

opts = subset.Options()
opts.flavor = "woff2"
opts.layout_features = []
opts.notdef_outline = False
opts.name_IDs = ["*"]
f2 = TTFont(OUT + ".ttf")
sub = subset.Subsetter(opts)
cps = sorted(set(newmap) | {0xFE0F, 0x200D})
sub.populate(unicodes=cps)
sub.subset(f2)
f2.flavor = "woff2"
f2.save(OUT)
rng = ", ".join(f"U+{c:X}" for c in cps)
open(CSS_OUT, "w").write(rng)
print("glyphs", len(chosen), "codepoints", len(cps))
head = f2["head"]; hhea = f2["hhea"]
print("upm", head.unitsPerEm, "asc", hhea.ascent, "desc", hhea.descent)
