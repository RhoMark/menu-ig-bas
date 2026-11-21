#!/usr/bin/env node
/**
 * audit-nutrition-duplicates.mjs — Fiches nutritionnelles (data-glycemic) en double.
 *
 * Un même produit peut avoir plusieurs fiches (« flocons d'avoine » IG 55 et
 * « flocons d'avoine complets » IG 40) : selon le nom écrit dans la recette, la
 * charge glycémique change. Ce script, avec le VRAI code de l'app
 * (dataRef.glycemic, nutriGrams) :
 *   1. regroupe les fiches qui désignent le même produit (clé normalisée :
 *      sans accents, singulier, sans qualificatifs neutres) ;
 *   2. pour chaque groupe dont les valeurs diffèrent, montre l'usage réel dans le
 *      catalogue (lignes de recettes, grammes, glucides disponibles en jeu) ;
 *   3. --resolution : liste les noms de recettes résolus par « dépouillement »
 *      (fallback) vers une fiche dont le nom diffère beaucoup (risque de mauvaise
 *      fiche, ex. « Pousses de soja » → « soja » en grain).
 *
 * Usage : node scripts/audit-nutrition-duplicates.mjs [--json] [--resolution]
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { dataRef, canonicalName, nutriGrams } from "./recipe-cg.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "index.html"), "utf8");
const gly = JSON.parse(html.match(/<script type="application\/json" id="data-glycemic">\s*([\s\S]*?)\s*<\/script>/)[1]).items;
const win = {};
new Function("window", readFileSync(join(ROOT, "data/recipes.js"), "utf8"))(win);
const RECIPES = win.__DATA_RECIPES.items;

// Mots qui ne changent pas le produit acheté / sa composition
const NEUTRAL = new Set(["frais", "fraiche", "fraiches", "nature", "entier", "entiere", "entiers", "entieres",
  "en", "boite", "conserve", "bocal", "au", "naturel", "de", "d", "du", "des", "la", "le", "les", "l", "a",
  "egoutte", "egouttes", "egouttee", "egouttees", "denoyaute", "denoyautee", "denoyautes", "denoyautees",
  "decortique", "decortiques", "decortiquee", "decortiquees", "ecosse", "ecosses", "surgele", "surgeles",
  "surgelee", "surgelees", "congele", "congeles", "bio", "type", "classique", "standard"]);
const norm = id => canonicalName(id).replace(/['’]/g, " ").split(/\s+/)
  .map(w => (w.length > 3 ? w.replace(/[sx]$/, "") : w)).filter(w => w && !NEUTRAL.has(w)).sort().join(" ");

// Usage : chaque ligne de recette → fiche résolue
const usage = new Map(); // id → {lines, grams, names:Set}
const resolutions = [];
for (const r of RECIPES) for (const [name, qty, unit] of r.ing) {
  const canon = canonicalName(name);
  const g = dataRef.glycemic(canon);
  if (!g) continue;
  const grams = nutriGrams(name, qty, unit, g) ?? dataRef.qtyToGrams(name, qty, unit) ?? 0;
  const u = usage.get(g.id) || { lines: 0, grams: 0, names: new Set() };
  u.lines++; u.grams += grams; u.names.add(name); usage.set(g.id, u);
  if (canonicalName(g.id) !== canon) resolutions.push({ name, canon, id: g.id });
}

const groups = {};
for (const g of gly) (groups[norm(g.id)] ||= []).push(g);
const fmt = g => `IG ${g.ig ?? "?"} · gluc ${g.carbsPer100g} · prot ${g.proteinPer100g} · lip ${g.fatPer100g}`;
const differ = list => new Set(list.map(g => [g.ig, g.carbsPer100g, g.proteinPer100g, g.fatPer100g].join("|"))).size > 1;

const out = [];
for (const [k, list] of Object.entries(groups)) {
  if (list.length < 2 || !differ(list)) continue;
  const rows = list.map(g => {
    const u = usage.get(g.id) || { lines: 0, grams: 0, names: new Set() };
    return { id: g.id, ig: g.ig, carbs: g.carbsPer100g, prot: g.proteinPer100g, fat: g.fatPer100g,
      cookedYield: g.cookedYield, src: g.src, lines: u.lines, grams: Math.round(u.grams), names: [...u.names].slice(0, 6) };
  });
  const used = rows.filter(r => r.lines > 0).length;
  // Écart de CG potentiel : glucides × IG, max − min, pondéré par les grammes utilisés
  const cgPer100 = rows.map(r => (r.carbs || 0) * (r.ig || 0) / 100);
  const spread = Math.max(...cgPer100) - Math.min(...cgPer100);
  const totalGrams = rows.reduce((s, r) => s + r.grams, 0);
  out.push({ key: k, used, spread: +spread.toFixed(1), impact: Math.round(spread * totalGrams / 100), rows });
}
out.sort((a, b) => b.impact - a.impact || b.used - a.used);

if (process.argv.includes("--json")) { console.log(JSON.stringify(out, null, 1)); process.exit(0); }
// --check (CI) : un nom de recette ne doit JAMAIS retomber, par dépouillement, sur
// une fiche générique d'un AUTRE produit (« Pomme de terre Charlotte » → « pomme »,
// « Lait de soja » → « lait » de vache, « Pâte de soja » → « pâtes »). Ajouter alors
// une fiche explicite (data-glycemic) pour ce nom.
const GENERIC_TRAPS = ["pates", "pate", "lait", "beurre", "pomme", "feuille", "soja", "creme", "sauce", "farine", "riz"];
if (process.argv.includes("--check")) {
  const bad = new Map();
  for (const x of resolutions) {
    if (!GENERIC_TRAPS.includes(x.id) || x.canon === x.id) continue;
    if (x.id === "feuille" && /^feuille de (laurier|pandan|gelatine)/.test(x.canon)) continue; // quantités négligeables
    // Piège = le nom continue par un complément qui change le produit (« pomme DE terre »,
    // « lait DE soja », « pâte À tartiner ») ; « Pomme verte » → « pomme » est correct.
    const head = x.id.replace(/s$/, "");
    const m = x.canon.match(new RegExp(`^${head}s? (\\S+)`));
    if (!m || !(["de", "d", "a", "au", "aux"].includes(m[1]) || /^lait concentre/.test(x.canon))) continue;
    bad.set(x.canon, x.id);
  }
  for (const [c, id] of bad) console.log(`❌ « ${c} » utilise la fiche générique « ${id} » : ajouter une fiche explicite`);
  console.log(bad.size ? `\n${bad.size} nom(s) sur une mauvaise fiche.` : "✅ Fiches nutritionnelles : aucun nom sur une fiche générique d'un autre produit.");
  process.exit(bad.size ? 1 : 0);
}
if (process.argv.includes("--resolution")) {
  const seen = new Map();
  for (const x of resolutions) seen.set(`${x.canon} → ${x.id}`, (seen.get(`${x.canon} → ${x.id}`) || 0) + 1);
  for (const [k, n] of [...seen].sort((a, b) => b[1] - a[1])) console.log(`${String(n).padStart(4)}  ${k}`);
  process.exit(0);
}
let n = 0;
for (const g of out) {
  if (!g.used) continue;
  n++;
  console.log(`\n■ ${g.key}  (écart CG/100 g : ${g.spread} · impact catalogue : ${g.impact})`);
  for (const r of g.rows) console.log(`   ${r.lines ? "●" : "○"} ${r.id.padEnd(34)} ${fmt({ ig: r.ig, carbsPer100g: r.carbs, proteinPer100g: r.prot, fatPer100g: r.fat })}`
    + `${r.cookedYield ? ` · cookedYield ${r.cookedYield}` : ""}  — ${r.lines} lignes, ${r.grams} g${r.src ? ` [${r.src}]` : ""}`);
}
console.log(`\n${n} groupe(s) de fiches en double utilisées par le catalogue (sur ${out.length} groupes aux valeurs divergentes).`);
