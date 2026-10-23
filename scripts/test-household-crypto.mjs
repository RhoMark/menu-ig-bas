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

// ── S5 — époque dans l'AAD ──
await check("époque 2 : ouverture OK ; époque falsifiée → WRONG_KEY", async () => {
  const e2 = await hc.seal(household, hid, keyA, 2);
  assert.equal(e2.epoch, 2);
  assert.deepEqual(await hc.open(e2, keyA), household);
  await rejects(() => hc.open({...e2, epoch: 1}, keyA), "WRONG_KEY");
  await rejects(() => hc.open({...e2, epoch: undefined}, keyA), "WRONG_KEY");
});

// ── S5 — emballage de clé (rotation) ──
const ecdh = () => crypto.subtle.generateKey({name: "ECDH", namedCurve: "P-256"}, false, ["deriveBits"]);
const pubB64 = async kp => hc.toB64url(new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey)));
await check("rotation : l'admin emballe la nouvelle clé, B la déballe", async () => {
  const admin = await ecdh(), devB = await ecdh();
  const k2 = hc.newKey();
  const wrap = await hc.wrapKey(admin.privateKey, await pubB64(devB), k2, hid, 1, "devB");
  assert.deepEqual(await hc.unwrapKey(devB.privateKey, await pubB64(admin), wrap, hid, 1, "devB"), k2);
});
await check("rotation : un autre appareil (ou mauvais contexte) ne peut pas déballer", async () => {
  const admin = await ecdh(), devB = await ecdh(), devC = await ecdh();
  const wrap = await hc.wrapKey(admin.privateKey, await pubB64(devB), hc.newKey(), hid, 1, "devB");
  const adminPub = await pubB64(admin);
  await rejects(() => hc.unwrapKey(devC.privateKey, adminPub, wrap, hid, 1, "devB"), "UNWRAP_FAILED");
  await rejects(() => hc.unwrapKey(devB.privateKey, adminPub, wrap, hid, 2, "devB"), "UNWRAP_FAILED");
});

// ── S5 — fusion 3 voies ──
const M = (b, l, r) => hc.mergeHousehold(b, l, r);
const fam = (allergiesA, extra = {}) => ({members: [{id: 1, name: "Zéphyrine", allergies: allergiesA}, {id: 2, name: "Barnabé", allergies: []}], favorites: ["a"], menus: {w1: {mon: "x"}}, ...extra});
await check("fusion : favoris ajoutés des deux côtés → tous gardés", () => {
  const {merged} = M(fam([]), fam([], {favorites: ["a", "b"]}), fam([], {favorites: ["a", "c"]}));
  assert.deepEqual(merged.favorites, ["a", "b", "c"]);
});
await check("fusion : allergie ajoutée sur 2 appareils pour 2 membres → les deux gardées", () => {
  const l = fam(["peanuts"]); const r = fam([]); r.members[1].allergies = ["gluten"];
  const {merged, conflicts} = M(fam([]), l, r);
  assert.deepEqual(merged.members[0].allergies, ["peanuts"]);
  assert.deepEqual(merged.members[1].allergies, ["gluten"]);
  assert.equal(conflicts.length, 0);
});
await check("fusion : suppression d'allergie par l'admin + ajout ailleurs → suppression respectée", () => {
  const {merged} = M(fam(["peanuts"]), fam([]), fam(["peanuts", "fish"]));
  assert.deepEqual(merged.members[0].allergies, ["fish"]);
});
await check("fusion : semaine ajoutée ici + semaine modifiée là-bas → les deux", () => {
  const l = fam([], {menus: {w1: {mon: "x"}, w2: {tue: "y"}}});
  const r = fam([], {menus: {w1: {mon: "z"}}});
  assert.deepEqual(M(fam([]), l, r).merged.menus, {w1: {mon: "z"}, w2: {tue: "y"}});
});
await check("fusion : membre retiré à distance, non modifié ici → retiré", () => {
  const r = fam([]); r.members = [r.members[0]];
  assert.equal(M(fam([]), fam([]), r).merged.members.length, 1);
});
await check("fusion : membre retiré à distance mais modifié ici → conservé", () => {
  const l = fam([]); l.members[1].allergies = ["eggs"];
  const r = fam([]); r.members = [r.members[0]];
  const {merged} = M(fam([]), l, r);
  assert.deepEqual(merged.members.find(m => m.id === 2)?.allergies, ["eggs"]);
});
await check("fusion : même champ modifié des deux côtés → local gagne + conflit compté", () => {
  const l = fam([]); l.members[0].name = "Zéph";
  const r = fam([]); r.members[0].name = "Zézé";
  const {merged, conflicts} = M(fam([]), l, r);
  assert.equal(merged.members[0].name, "Zéph"); assert.equal(conflicts.length, 1);
});
await check("fusion : sans base (1re synchro) → le foyer partagé fait foi ; sans distant → local", () => {
  assert.equal(M(null, fam(["x"]), fam([])).merged.members[0].allergies.length, 0);
  assert.equal(M(null, fam(["x"]), null).merged.members[0].allergies[0], "x");
});

// Import d'une sauvegarde sur un appareil relié (bug V2.113.1 : l'import effaçait le lien)
const v2 = (house, device) => ({schema: 2, session: {activeHouseholdId: "h1", activeUserId: "u1"},
  users: {u1: {id: "u1", householdId: "h1", ...(device ? {device} : {})}}, households: {h1: {id: "h1", ...house}}});
const link = {hid: "hh_x", founderMemberId: 1};
const devSrv = {deviceId: "dev1", mode: "personal", boundMemberId: 1, server: {hid: "hh_x", approved: true, version: 7}};
await check("import : lien de foyer (syncMeta + appareil/serveur) conservé", () => {
  const cur = v2({syncMeta: link, ...fam(["peanuts"])}, devSrv);
  const imp = v2({...fam(["peanuts"]), menus: {w9: {mon: "b1"}}});
  const out = hc.keepLinkOnImport(cur, imp);
  assert.deepEqual(out.households.h1.syncMeta, link);
  assert.deepEqual(out.users.u1.device, devSrv);
  assert.deepEqual(out.households.h1.menus, {w9: {mon: "b1"}});
  assert.equal(imp.households.h1.syncMeta, undefined); // entrée non modifiée
});
await check("import : une allergie connue n'est jamais retirée par l'import", () => {
  const cur = v2({syncMeta: link, ...fam(["peanuts", "fish"])}, devSrv);
  const out = hc.keepLinkOnImport(cur, v2(fam(["gluten"])));
  assert.deepEqual(out.households.h1.members[0].allergies, ["gluten", "peanuts", "fish"]);
});
await check("import : appareil non relié → import inchangé", () => {
  const imp = v2(fam(["gluten"]));
  assert.equal(hc.keepLinkOnImport(v2(fam(["peanuts"])), imp), imp);
});

console.log("━".repeat(28));
if (process.exitCode) { console.error("❌ householdCrypto : échec"); process.exit(1); }
console.log(`✅ householdCrypto : ${ok} vérifications OK`);
