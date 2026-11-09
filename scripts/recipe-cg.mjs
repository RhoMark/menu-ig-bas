#!/usr/bin/env node
/**
 * recipe-cg.mjs — Charge glycémique d'une recette calculée par le VRAI code de
 * l'app (fonctions extraites d'index.html : canonicalName, REF, dataRef,
 * computeRecipeGlycemic, glycemicTierForMeal). Aucune copie à maintenir :
 * le lint et l'app ne peuvent plus diverger (bug V2.99.19 → V2.126 : le lint
 * divisait la CG par 4 alors que les quantités sont PAR PORTION).
 *
 * Usage :
 *   node scripts/recipe-cg.mjs < recettes.json          # [{id,type,ing,…}] → JSON [{id,type,cg,tier}]
 *   node scripts/recipe-cg.mjs --catalogue              # tout data/recipes.js
 * Les quantités des recettes sont PAR PORTION (comme dans l'app).
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const html = readFileSync(join(ROOT, "index.html"), "utf8");

// Extrait une déclaration de haut niveau (function / const) avec appariement
// des accolades, en ignorant chaînes, gabarits, commentaires et regex.
export function extract(name) {
  const re = new RegExp(`^(function ${name}\\(|const ${name}\\s*=)`, "m");
  const m = re.exec(html);
  if (!m) throw new Error(`déclaration introuvable : ${name}`);
  let i = m.index, depth = 0, started = false;
  const isConst = m[0].startsWith("const");
  for (; i < html.length; i++) {
    const c = html[i], prev = html[i - 1];
    if (c === "/" && html[i + 1] === "/") { i = html.indexOf("\n", i); continue; }
    if (c === "/" && html[i + 1] === "*") { i = html.indexOf("*/", i) + 1; continue; }
    if (c === '"' || c === "'" || c === "`") {
      for (i++; i < html.length && html[i] !== c; i++) if (html[i] === "\\") i++;
      continue;
    }
    if (c === "/" && /[=(,:!&|?;{}\[\n]\s*$/.test(html.slice(Math.max(0, i - 20), i))) { // littéral regex
      let cls = false;
      for (i++; i < html.length; i++) {
        if (html[i] === "\\") { i++; continue; }
        if (html[i] === "[") cls = true; else if (html[i] === "]") cls = false;
        else if (html[i] === "/" && !cls) break;
      }
      continue;
    }
    if (c === "{" || c === "(" || c === "[") { depth++; started = true; }
    else if (c === "}" || c === ")" || c === "]") {
      depth--;
      if (started && depth === 0 && !isConst && c === "}") return html.slice(m.index, i + 1);
    } else if (isConst && depth === 0 && c === ";") return html.slice(m.index, i + 1); // « started » non requis : const X = /regex/;
    void prev;
  }
  throw new Error(`fin introuvable : ${name}`);
}

const block = id => {
  const m = html.match(new RegExp(`<script type="application/json" id="${id}">\\s*([\\s\\S]*?)\\s*</script>`));
  return m ? JSON.parse(m[1]) : null;
};
const NEGLIGIBLE_DECLS = ["NEGLIGIBLE_NUTRI_KEYWORDS", "isNutriNegligible"];
const src = [
  "const console = {error() {}, warn() {}, log() {}};",
  "function loadRefBlock(id, fallback) { return BLOCK(id) || fallback; }",
  ...["canonicalName", "PRODUCE_PREP_RE", "stripProducePrep", "HERB_BOUQUET_G", "HERB_FEUILLE_G", "HERB_BRANCHE_G",
      "REF", "dataRef", "COOKED_LINE_RE", "nutriGrams", "computeRecipeGlycemic", "CG_TIERS_BY_MEAL", "glycemicTierForMeal",
      ...NEGLIGIBLE_DECLS, "computeRecipeMacros"].map(extract),
  "return {computeRecipeGlycemic, glycemicTierForMeal, computeRecipeMacros, canonicalName, dataRef, nutriGrams};",
].join("\n");
export const { computeRecipeGlycemic, glycemicTierForMeal, computeRecipeMacros, canonicalName, dataRef, nutriGrams } = new Function("BLOCK", src)(block);

export function recipeCg(recipes) {
  return recipes.map(r => {
    const g = computeRecipeGlycemic(r);
    const m = computeRecipeMacros(r);
    return { id: r.id, type: r.type, cg: g ? g.cg : null, tier: g ? glycemicTierForMeal(g.cg, r.type) : "unknown",
      kcalCalc: m ? m.kcal : null, kcal: r.kcal ?? null };
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  let recipes;
  if (process.argv.includes("--catalogue")) {
    globalThis.window = {};
    new Function("window", readFileSync(join(ROOT, "data/recipes.js"), "utf8"))(globalThis.window);
    recipes = globalThis.window.__DATA_RECIPES.items;
  } else {
    recipes = JSON.parse(readFileSync(0, "utf8"));
  }
  process.stdout.write(JSON.stringify(recipeCg(recipes)));
}
