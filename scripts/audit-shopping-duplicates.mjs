#!/usr/bin/env node
/**
 * audit-shopping-duplicates.mjs — Doublons de la liste de courses, calculés par
 * le VRAI code de l'app (aggregateShoppingList extrait d'index.html).
 *
 * Met TOUT le catalogue dans une liste de courses fictive (1 recette par « jour »)
 * puis signale :
 *   1. MÊME NOM sur plusieurs lignes (unités qui ne convergent pas : « Persil plat
 *      1 (≈100 g/pièce) » + « Persil plat 50 g »)  → BLOQUANT (exit 1)
 *   2. NOMS VOISINS : deux lignes qui ne diffèrent que par un qualificatif neutre
 *      (frais / fraîche…) → BLOQUANT
 *
 * Usage : node scripts/audit-shopping-duplicates.mjs [--verbose]
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { extract } from "./recipe-cg.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "index.html"), "utf8");
const block = id => {
  const m = html.match(new RegExp(`<script type="application/json" id="${id}">\\s*([\\s\\S]*?)\\s*</script>`));
  return m ? JSON.parse(m[1]) : null;
};
const win = {};
new Function("window", readFileSync(join(ROOT, "data/recipes.js"), "utf8"))(win);
const RECIPES = win.__DATA_RECIPES.items;

const names = ["canonicalName", "PRODUCE_PREP_RE", "stripProducePrep", "HERB_BOUQUET_G", "HERB_FEUILLE_G", "HERB_BRANCHE_G",
  "REF", "dataRef", "COOKED_LINE_RE", "nutriGrams", "SPOON_TO_GRAMS", "SPOON_TO_ML", "LIQUID_AROMATIC_KEYS", "isLiquidAromatic",
  "HERB_KEYWORDS", "isHerbFresh", "ROOT_FRESH_KEYWORDS", "ROOT_CM_TO_G", "isFreshRoot", "unitConvertForAggregation",
  "displayCanonName", "pickDisplayLabel", "JUICE_ML_PER_FRUIT", "VOLUME_TO_ML", "SHOPPING_ALIASES", "citrusJuiceToFruit", "mergeSameItemLines", "formatQty", "formatSpoonHint", "formatQtyShopping", "aggregateShoppingList"];
const src = [
  "const console = {error() {}, warn() {}, log() {}};",
  "function loadRefBlock(id, fallback) { return BLOCK(id) || fallback; }",
  // Stubs : 1 « jour » par recette, 1 repas, 1 portion, pas d'invités ni de fête.
  "const DAYS = RECIPES.map(r => r.id);",
  "const getAllActiveSlots = () => ['x']; const defaultGuestRatios = () => ({});",
  "const slotIsAperoDinatoireOnMeal = () => false; const slotFeastObj = () => null; const slotApero = () => null;",
  "const mealEquivalents = () => 1; const scaleQty = (q, m) => q * m;",
  ...names.map(extract),
  "return {aggregateShoppingList, formatQtyShopping, canonicalName};",
].join("\n");
const app = new Function("BLOCK", "RECIPES", src)(block, RECIPES);

const week = Object.fromEntries(RECIPES.map(r => [r.id, {x: r.id}]));
const byCat = app.aggregateShoppingList(week, {});

// Qualificatifs qui ne changent pas l'article acheté (le rayon frais ne vend pas de « persil sec »).
const NEUTRAL = /\b(frais|fraiche|fraiches|fraichement)\b/g;
const norm = s => app.canonicalName(s).replace(NEUTRAL, " ").replace(/\s+/g, " ").trim();

const verbose = process.argv.includes("--verbose");
// --show <mot> : affiche les lignes dont le nom contient <mot> (contrôle visuel).
const showIdx = process.argv.indexOf("--show");
if (showIdx > 0) {
  const w = app.canonicalName(process.argv[showIdx + 1] || "");
  for (const [cat, items] of Object.entries(byCat)) for (const it of items)
    if (app.canonicalName(it.name).includes(w)) console.log(`[${cat}] ${it.label} — ${app.formatQtyShopping(it.qty, it.unit, it.name, cat)}`);
}
let problems = 0;
for (const [cat, items] of Object.entries(byCat)) {
  const byName = {}, byNorm = {};
  for (const it of items) {
    (byName[it.name] ||= []).push(it);
    (byNorm[norm(it.name)] ||= new Set()).add(it.name);
  }
  for (const [n, list] of Object.entries(byName)) {
    if (list.length < 2) continue;
    problems++;
    console.log(`❌ [${cat}] « ${n} » sur ${list.length} lignes : ` +
      list.map(i => app.formatQtyShopping(i.qty, i.unit, i.name, cat)).join("  +  "));
  }
  for (const [k, set] of Object.entries(byNorm)) {
    // Laitiers exclus : « Fromage de chèvre frais » ≠ « Fromage de chèvre » (affiné).
    if (set.size < 2 || cat === "dairy") continue;
    problems++;
    console.log(`❌ [${cat}] noms voisins (« ${k} ») : ${[...set].map(s => `« ${s} »`).join(", ")}`);
  }
}
// 3. MÊME ARTICLE dans deux rayons (« Lait de coco » en Épicerie ET en Crèmerie).
const cats = {};
for (const [cat, items] of Object.entries(byCat)) for (const it of items) (cats[it.label] ||= new Set()).add(cat); // libellé affiché : « Gingembre » (rayon frais) ≠ « Gingembre moulu » (épices), même nom canonique
for (const [n, set] of Object.entries(cats)) {
  if (set.size < 2) continue;
  problems++;
  console.log(`❌ « ${n} » dans ${set.size} rayons : ${[...set].join(", ")}`);
}
if (verbose) console.log(Object.values(byCat).flat().length, "lignes au total");
console.log(problems ? `\n${problems} doublon(s) dans la liste de courses.` : "✅ Liste de courses : aucun doublon.");
process.exit(problems ? 1 : 0);
