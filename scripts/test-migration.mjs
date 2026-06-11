#!/usr/bin/env node
/**
 * test-migration.mjs — Phase 0.7 (B4)
 *
 * Garantit qu'une migration de schéma user-data ne perd AUCUNE donnée.
 * Personne ne sauvegarde manuellement → une régression de migration = perte
 * sèche chez les beta testeurs. Ce test est BLOQUANT en CI.
 *
 * Principe : on extrait les vraies fonctions de migration depuis index.html
 * (pas de copie qui dériverait), on les exécute sur des fixtures représentant
 * d'anciens états V1, et on asserte que chaque compteur (membres, semaines de
 * menu, notes, journal, garde-manger, onboarding) est conservé à l'identique.
 *
 * Quand on introduira une migration V2→V3, ajouter ses fonctions à NEEDED et
 * une fixture v2-*.json, et asserter la conservation sur la nouvelle chaîne.
 *
 * Usage : node scripts/test-migration.mjs
 * Exit  : 0 = zéro perte ; 1 = perte détectée / extraction impossible.
 */

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const INDEX = join(ROOT, "index.html");
const FIXTURES = join(__dirname, "fixtures");

// Fonctions / constantes pures à extraire de index.html (ordre = dépendances).
const NEEDED = [
  { name: "GUEST_TYPES", kind: "const" },
  { name: "makeId", kind: "function" },
  { name: "defaultGuestRatios", kind: "function" },
  { name: "emptyHouseholdPreferences", kind: "function" },
  { name: "emptyHousehold", kind: "function" },
  { name: "migrateV1toV2", kind: "function" },
  { name: "applyV2Backfills", kind: "function" },
  { name: "projectRuntime", kind: "function" },
];

// ── Extracteur conscient des chaînes / commentaires ───────────────────────
// Renvoie la sous-chaîne depuis `open` (inclus) jusqu'au `close` apparié, en
// ignorant accolades/crochets situés dans des strings, templates ou commentaires.
function extractBalanced(src, startIdx, open, close) {
  let depth = 0, i = startIdx;
  let str = null; // "'" | '"' | "`" | "//" | "/*"
  for (; i < src.length; i++) {
    const c = src[i], n = src[i + 1];
    if (str === "//") { if (c === "\n") str = null; continue; }
    if (str === "/*") { if (c === "*" && n === "/") { str = null; i++; } continue; }
    if (str) { // dans une string
      if (c === "\\") { i++; continue; }
      if (c === str) str = null;
      continue;
    }
    if (c === "/" && n === "/") { str = "//"; i++; continue; }
    if (c === "/" && n === "*") { str = "/*"; i++; continue; }
    if (c === "'" || c === '"' || c === "`") { str = c; continue; }
    if (c === open) depth++;
    else if (c === close) { depth--; if (depth === 0) return src.slice(startIdx, i + 1); }
  }
  throw new Error(`Bloc non équilibré à partir de l'index ${startIdx}`);
}

function extractSnippet(src, { name, kind }) {
  if (kind === "function") {
    const re = new RegExp(`function\\s+${name}\\s*\\(`);
    const m = re.exec(src);
    if (!m) throw new Error(`fonction ${name} introuvable dans index.html`);
    const braceStart = src.indexOf("{", m.index);
    const body = extractBalanced(src, braceStart, "{", "}");
    return src.slice(m.index, braceStart) + body;
  } else { // const tableau
    const re = new RegExp(`const\\s+${name}\\s*=\\s*\\[`);
    const m = re.exec(src);
    if (!m) throw new Error(`const ${name} introuvable dans index.html`);
    const brkStart = src.indexOf("[", m.index);
    const arr = extractBalanced(src, brkStart, "[", "]");
    return `const ${name} = ${arr};`;
  }
}

// ── Construit un module exécutable à partir des snippets extraits ─────────
function buildMigrationModule() {
  const src = readFileSync(INDEX, "utf8");
  const snippets = NEEDED.map(d => extractSnippet(src, d)).join("\n\n");
  const factory = new Function(`
    ${snippets}
    return { migrateV1toV2, applyV2Backfills, projectRuntime };
  `);
  return factory();
}

// ── Compteurs invariants d'un état (V1 brut ou runtime projeté) ───────────
function countersV1(v1) {
  const members = (v1.profile && Array.isArray(v1.profile.members))
    ? v1.profile.members.length : 1; // migrateV1toV2 met 1 membre par défaut
  return {
    members,
    menuWeeks: Object.keys(v1.menus || {}).length,
    ratings: Object.keys(v1.ratings || {}).length,
    journal: Object.keys(v1.journal || {}).length,
    pantry: Object.keys(v1.pantryChecks || {}).length,
    onboarded: !!v1.onboarded,
  };
}
function countersRuntime(rt) {
  return {
    members: (rt.profile && Array.isArray(rt.profile.members)) ? rt.profile.members.length : 0,
    menuWeeks: Object.keys(rt.menus || {}).length,
    ratings: Object.keys(rt.ratings || {}).length,
    journal: Object.keys(rt.journal || {}).length,
    pantry: Object.keys(rt.pantryChecks || {}).length,
    onboarded: !!rt.onboarded,
  };
}

function main() {
  let mod;
  try {
    mod = buildMigrationModule();
  } catch (e) {
    console.error("❌ Extraction des fonctions de migration impossible :", e.message);
    process.exit(1);
  }

  let fixtures;
  try {
    fixtures = readdirSync(FIXTURES).filter(f => f.endsWith(".json"));
  } catch {
    console.error("❌ Dossier de fixtures introuvable :", FIXTURES);
    process.exit(1);
  }
  if (fixtures.length === 0) {
    console.error("❌ Aucune fixture de migration. Ajoute des exports V1 dans scripts/fixtures/.");
    process.exit(1);
  }

  let failures = 0;
  for (const f of fixtures.sort()) {
    const v1 = JSON.parse(readFileSync(join(FIXTURES, f), "utf8"));
    const before = countersV1(v1);
    let after;
    try {
      const v2 = mod.applyV2Backfills(mod.migrateV1toV2(v1));
      after = countersRuntime(mod.projectRuntime(v2));
    } catch (e) {
      console.error(`❌ ${f} : migration a levé une erreur — ${e.message}`);
      failures++; continue;
    }
    const diffs = Object.keys(before).filter(k => String(before[k]) !== String(after[k]));
    if (diffs.length) {
      failures++;
      console.error(`❌ ${f} : perte de données sur ${diffs.join(", ")}`);
      diffs.forEach(k => console.error(`     ${k}: V1=${before[k]} → runtime=${after[k]}`));
    } else {
      console.log(`✅ ${f} : zéro perte (membres ${after.members}, semaines ${after.menuWeeks}, notes ${after.ratings}, journal ${after.journal}, garde-manger ${after.pantry})`);
    }
  }

  console.log("━".repeat(28));
  if (failures) {
    console.error(`❌ ${failures} fixture(s) en échec — migration NON sûre.`);
    process.exit(1);
  }
  console.log(`✅ ${fixtures.length} fixture(s) migrée(s) sans perte.`);
  process.exit(0);
}

main();
