#!/usr/bin/env node
/**
 * test-household-crypto.mjs — Phase 2·L (S3)
 *
 * Vérifie le module `householdCrypto` (clé de foyer + fichier foyer chiffré)
 * EXTRAIT de index.html (bloc entre les marqueurs @@household-crypto), donc
 * le vrai code, pas une copie. WebCrypto natif de Node ≥ 20.
 *
 * Scénario « 2 appareils » : A crée la clé, l'encode en QR et en code de
 * secours ; B la décode et ouvre le blob scellé par A → contenu identique.
 * Cas d'échec : mauvaise clé, blob altéré, blob recollé sur un autre foyer,
 * faute de frappe dans le code, QR étranger. Aucun prénom en clair dans le blob.
 *
 * Usage : node scripts/test-household-crypto.mjs   (exit 0 = OK, 1 = échec)
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(ROOT, "index.html"), "utf8");
const m = src.match(/\/\/ @@household-crypto:start\n([\s\S]*?)\/\/ @@household-crypto:end/);
if (!m) { console.error("❌ Bloc @@household-crypto introuvable dans index.html"); process.exit(1); }
const hc = new Function(`${m[1]}\nreturn householdCrypto;`)();

const household = {
  id: "h_test",
  members: [
    {id: 1, name: "Zéphyrine", birthYear: 1985, allergies: ["peanut"], healthProfile: "sopk"},
    {id: 2, name: "Barnabé", birthYear: 2011, allergies: [], healthProfile: "healthy"},
  ],
  menus: {"2026-10-19": {mon: {dinner: "d428"}}},
  ratings: {d428: {1: 5, 2: 4}},
  syncMeta: {hid: null, founderMemberId: 1},
};

let ok = 0;
async function check(label, fn) {
  try { await fn(); ok++; console.log(`✅ ${label}`); }
  catch (e) { console.error(`❌ ${label} — ${e.message}`); process.exitCode = 1; }
}
async function rejects(fn, code) {
  try { await fn(); } catch (e) { assert.equal(e.code, code, `code attendu ${code}, obtenu ${e.code}`); return; }
  throw new Error(`aurait dû échouer (${code})`);
}

// Appareil A (fondateur)
const hid = hc.newHid();
const keyA = hc.newKey();
const env = await hc.seal(household, hid, keyA);
const invite = hc.inviteString(hid, keyA);
const code = await hc.recoveryCode(keyA);

await check("hid opaque (hh_ + 22 caractères)", () => assert.match(hid, /^hh_[A-Za-z0-9_-]{22}$/));
await check("aucun prénom / allergie en clair dans le blob", () => {
  const s = JSON.stringify(env);
  for (const w of ["Zéphyrine", "Barnabé", "peanut", "sopk", "d428"]) assert.ok(!s.includes(w), w);
});
await check("B rejoint par QR → contenu identique", async () => {
  const {hid: h, rawKey} = hc.parseInvite(invite);
  assert.equal(h, hid);
  assert.deepEqual(await hc.open(env, rawKey), household);
});
await check("B rejoint par code de secours → contenu identique", async () => {
  assert.match(code, /^([0-9A-Z]{5}-){10}[0-9A-Z]{5}$/);
  assert.deepEqual(await hc.open(env, await hc.parseRecoveryCode(code)), household);
});
await check("code saisi en minuscules, sans tirets, O/0 confondus → accepté", async () => {
  const sloppy = code.replace(/-/g, " ").toLowerCase().replace(/0/g, "o");
  assert.deepEqual(await hc.open(env, await hc.parseRecoveryCode(sloppy)), household);
});
await check("faute de frappe dans le code → CODE_TYPO (avant déchiffrement)", async () => {
  const chars = code.split("");
  const i = chars.findIndex(c => c !== "-");
  chars[i] = chars[i] === "A" ? "B" : "A";
  await rejects(() => hc.parseRecoveryCode(chars.join("")), "CODE_TYPO");
});
await check("code tronqué → CODE_INVALID", () => rejects(() => hc.parseRecoveryCode(code.slice(0, 20)), "CODE_INVALID"));
await check("mauvaise clé → WRONG_KEY", () => rejects(() => hc.open(env, hc.newKey()), "WRONG_KEY"));
await check("blob altéré → WRONG_KEY", async () => {
  const ct = hc.fromB64url(env.ct); ct[5] ^= 1;
  await rejects(() => hc.open({...env, ct: hc.toB64url(ct)}, keyA), "WRONG_KEY");
});
await check("blob recollé sur un autre foyer (hid ≠ AAD) → WRONG_KEY", () =>
  rejects(() => hc.open({...env, hid: hc.newHid()}, keyA), "WRONG_KEY"));
await check("fichier étranger → FORMAT", () => rejects(() => hc.open({schema: "menu-ig-bas-export"}, keyA), "FORMAT"));
await check("QR étranger → INVITE_INVALID", () => rejects(() => hc.parseInvite("https://exemple.fr"), "INVITE_INVALID"));
await check("QR tronqué → INVITE_INVALID", () => rejects(() => hc.parseInvite(invite.slice(0, 40)), "INVITE_INVALID"));
await check("2 scellements du même foyer → IV différents", async () => {
  const env2 = await hc.seal(household, hid, keyA);
  assert.notEqual(env2.iv, env.iv);
});

console.log("━".repeat(28));
if (process.exitCode) { console.error("❌ householdCrypto : échec"); process.exit(1); }
console.log(`✅ householdCrypto : ${ok} vérifications OK`);
