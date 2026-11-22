#!/usr/bin/env node
/**
 * test-sync-server.mjs — Phase 2·L (S4)
 *
 * Teste le serveur de sync maison (sync-server/server.mjs) de bout en bout,
 * sur un port aléatoire et une base temporaire, avec le VRAI code client
 * (bloc householdCrypto extrait de index.html : joinSecret, signature…).
 * Vérifie : création, jonction en attente, approbation admin seulement,
 * 9ᵉ appareil refusé, signature falsifiée / rejeu / horloge décalée refusés,
 * appareil non approuvé sans accès au foyer, versions + conflit 409,
 * rétention, retrait d'appareil, et AUCUN prénom en clair dans la base.
 *
 * Usage : node --disable-warning=ExperimentalWarning scripts/test-sync-server.mjs
 */

import { readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { DatabaseSync } from "node:sqlite";
import assert from "node:assert/strict";
import { createSyncServer, MAX_DEVICES } from "../sync-server/server.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(ROOT, "index.html"), "utf8");
const m = src.match(/\/\/ @@household-crypto:start\n([\s\S]*?)\/\/ @@household-crypto:end/);
if (!m) { console.error("❌ Bloc @@household-crypto introuvable"); process.exit(1); }
const hc = new Function(`${m[1]}\nreturn householdCrypto;`)();

const dbPath = join(mkdtempSync(join(tmpdir(), "mij-sync-")), "sync.db");
let clock = Date.now();
const server = createSyncServer({ dbPath, now: () => clock });
await new Promise(r => server.listen(0, "127.0.0.1", r));
const BASE = `http://127.0.0.1:${server.address().port}`;

// ── Mini client : même protocole que LocalHomeTransport (index.html) ──
async function newDevice() {
  const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
  const raw = new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey));
  return { kp, pub: hc.toB64url(raw), id: await hc.deviceIdOf(raw), lastTs: 0 };
}
async function call(dev, method, path, body, { ts, tamper } = {}) {
  const text = body === undefined ? "" : JSON.stringify(body);
  const t = ts ?? Math.max(clock, dev.lastTs + 1);
  if (ts === undefined) dev.lastTs = t; // un horodatage forcé (tests rejeu/horloge) ne fait pas avancer le compteur
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, dev.kp.privateKey,
    new TextEncoder().encode(await hc.signingString(method, path, t, text))));
  const res = await fetch(BASE + path, { method, body: tamper ? text.replace("a", "b") : (text || undefined),
    headers: { "Content-Type": "application/json", "X-Mij-Device": dev.id, "X-Mij-Ts": String(t), "X-Mij-Sig": hc.toB64url(sig) } });
  return { status: res.status, body: await res.json() };
}

let ok = 0;
async function check(label, fn) {
  try { await fn(); ok++; console.log(`✅ ${label}`); }
  catch (e) { console.error(`❌ ${label} — ${e.message}`); process.exitCode = 1; }
}

const household = { id: "h_1", members: [{ id: 1, name: "Zéphyrine", allergies: ["peanuts"] }, { id: 2, name: "Barnabé" }], menus: { w: { mon: "d428" } } };
const hid = hc.newHid(), key = hc.newKey();
const secret = await hc.joinSecret(key);
const label = async txt => JSON.stringify(await hc.seal({ label: txt }, hid, key));
const A = await newDevice();

await check("A crée le foyer → admin approuvé", async () => {
  const r = await call(A, "POST", "/api/v1/households", { hid, pubkey: A.pub, labelCt: await label("PC de Zéphyrine"), joinVerifier: await hc.joinVerifier(secret) });
  assert.equal(r.status, 201); assert.equal(r.body.isAdmin, true); assert.equal(r.body.deviceId, A.id);
});
await check("foyer en double → 409", async () => {
  const r = await call(A, "POST", "/api/v1/households", { hid, pubkey: A.pub, joinVerifier: await hc.joinVerifier(secret) });
  assert.equal(r.status, 409);
});
let v1;
await check("A envoie le foyer chiffré (v1)", async () => {
  const r = await call(A, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: 0, envelope: await hc.seal(household, hid, key) });
  assert.equal(r.status, 200); v1 = r.body.version; assert.equal(v1, 1);
});
const B = await newDevice();
await check("B sans le joinSecret → refusé", async () => {
  const r = await call(B, "POST", "/api/v1/join", { pubkey: B.pub, joinSecret: hc.toB64url(hc.newKey()) });
  assert.equal(r.status, 403); assert.equal(r.body.error, "JOIN_DENIED");
});
await check("B avec le joinSecret (QR scanné) → en attente", async () => {
  const r = await call(B, "POST", "/api/v1/join", { pubkey: B.pub, joinSecret: secret, labelCt: await label("iPhone de Barnabé") });
  assert.equal(r.status, 202); assert.equal(r.body.hid, hid); assert.equal(r.body.approved, false);
});
await check("B en attente : voit son statut mais PAS le foyer", async () => {
  const me = await call(B, "GET", `/api/v1/households/${hid}/me`);
  assert.equal(me.status, 200); assert.equal(me.body.approved, false);
  const blob = await call(B, "GET", `/api/v1/households/${hid}/blob`);
  assert.equal(blob.status, 403); assert.equal(blob.body.error, "NOT_APPROVED");
});
await check("B ne peut pas s'approuver lui-même", async () => {
  const r = await call(B, "POST", `/api/v1/households/${hid}/devices/${B.id}/approve`);
  assert.equal(r.status, 403);
});
await check("A (admin) voit la demande de B et l'approuve", async () => {
  const list = await call(A, "GET", `/api/v1/households/${hid}/devices`);
  assert.equal(list.status, 200);
  const pending = list.body.devices.find(d => d.deviceId === B.id);
  assert.equal(pending.approved, false);
  assert.equal((await hc.open(JSON.parse(pending.labelCt), key)).label, "iPhone de Barnabé");
  const r = await call(A, "POST", `/api/v1/households/${hid}/devices/${B.id}/approve`);
  assert.equal(r.status, 200);
});
await check("B approuvé reçoit le foyer → identique après déchiffrement", async () => {
  const r = await call(B, "GET", `/api/v1/households/${hid}/blob`);
  assert.equal(r.status, 200); assert.equal(r.body.version, 1);
  assert.deepEqual(await hc.open(r.body.envelope, key), household);
});
await check("?since=1 → inchangé (rien à télécharger)", async () => {
  const r = await call(B, "GET", `/api/v1/households/${hid}/blob?since=1`);
  assert.equal(r.body.unchanged, true); assert.equal(r.body.envelope, undefined);
});
await check("B (non admin) ne peut pas approuver ni retirer un autre appareil", async () => {
  const r = await call(B, "DELETE", `/api/v1/households/${hid}/devices/${A.id}`);
  assert.equal(r.status, 403); assert.equal(r.body.error, "ADMIN_ONLY");
});
await check("conflit : B écrit sur une base périmée → 409", async () => {
  const ok2 = await call(A, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: 1, envelope: await hc.seal({ ...household, menus: {} }, hid, key) });
  assert.equal(ok2.body.version, 2);
  const r = await call(B, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: 1, envelope: await hc.seal(household, hid, key) });
  assert.equal(r.status, 409); assert.equal(r.body.error, "CONFLICT");
});
await check("enveloppe d'un autre foyer → refusée", async () => {
  const r = await call(A, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: 2, envelope: await hc.seal(household, hc.newHid(), key) });
  assert.equal(r.status, 400);
});
await check("signature falsifiée (corps modifié) → 401", async () => {
  const r = await call(A, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: 2, envelope: await hc.seal(household, hid, key) }, { tamper: true });
  assert.equal(r.status, 401);
});
await check("rejeu (horodatage déjà vu) → 401 REPLAY", async () => {
  assert.equal((await call(A, "GET", `/api/v1/households/${hid}/me`)).status, 200);
  const r = await call(A, "GET", `/api/v1/households/${hid}/me`, undefined, { ts: A.lastTs });
  assert.equal(r.body.error, "REPLAY");
});
await check("horloge décalée de 5 min → 401 CLOCK_SKEW", async () => {
  const r = await call(A, "GET", `/api/v1/households/${hid}/me`, undefined, { ts: clock + 300e3 });
  assert.equal(r.body.error, "CLOCK_SKEW");
});
await check(`limite ${MAX_DEVICES} appareils (en attente compris) → 9ᵉ refusé`, async () => {
  for (let i = 3; i <= MAX_DEVICES; i++) {
    const d = await newDevice();
    assert.equal((await call(d, "POST", "/api/v1/join", { pubkey: d.pub, joinSecret: secret })).status, 202);
  }
  const ninth = await newDevice();
  const r = await call(ninth, "POST", "/api/v1/join", { pubkey: ninth.pub, joinSecret: secret });
  assert.equal(r.status, 409); assert.equal(r.body.error, "DEVICE_LIMIT");
});
await check("S6 : /me donne le nombre d'appareils admin (1)", async () => {
  const r = await call(A, "GET", `/api/v1/households/${hid}/me`);
  assert.equal(r.status, 200); assert.equal(r.body.adminCount, 1);
});
await check("S6 : B (non admin) ne peut pas se rendre admin", async () => {
  const r = await call(B, "POST", `/api/v1/households/${hid}/devices/${B.id}/admin`, { isAdmin: true });
  assert.equal(r.status, 403); assert.equal(r.body.error, "ADMIN_ONLY");
});
await check("S6 : A rend B admin → 2 admins, B peut approuver ; A ne peut pas être rétrogradé s'il est le dernier", async () => {
  assert.equal((await call(A, "POST", `/api/v1/households/${hid}/devices/${B.id}/admin`, { isAdmin: "oui" })).status, 400);
  assert.equal((await call(A, "POST", `/api/v1/households/${hid}/devices/${B.id}/admin`, { isAdmin: true })).status, 200);
  const me = await call(B, "GET", `/api/v1/households/${hid}/me`);
  assert.equal(me.body.isAdmin, true); assert.equal(me.body.adminCount, 2);
  assert.equal((await call(B, "POST", `/api/v1/households/${hid}/devices/${B.id}/admin`, { isAdmin: false })).status, 200);
  const last = await call(A, "POST", `/api/v1/households/${hid}/devices/${A.id}/admin`, { isAdmin: false });
  assert.equal(last.status, 409); assert.equal(last.body.error, "LAST_ADMIN");
});
await check("retrait de B par l'admin → B n'a plus accès", async () => {
  assert.equal((await call(A, "DELETE", `/api/v1/households/${hid}/devices/${B.id}`)).status, 200);
  const r = await call(B, "GET", `/api/v1/households/${hid}/blob`);
  assert.equal(r.status, 403); assert.equal(r.body.error, "UNKNOWN_DEVICE");
});
await check("le dernier admin ne peut pas se retirer", async () => {
  const r = await call(A, "DELETE", `/api/v1/households/${hid}/devices/${A.id}`);
  assert.equal(r.status, 409); assert.equal(r.body.error, "LAST_ADMIN");
});
await check("rétention : max 3 versions, purge > 30 j sauf la dernière", async () => {
  for (let base = 2; base < 6; base++) {
    assert.equal((await call(A, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: base, envelope: await hc.seal(household, hid, key) })).status, 200);
  }
  const db = new DatabaseSync(dbPath);
  assert.deepEqual(db.prepare("SELECT version FROM blobs WHERE hid = ? ORDER BY version").all(hid).map(r => r.version), [4, 5, 6]);
  clock += 31 * 24 * 3600e3;
  assert.equal((await call(A, "PUT", `/api/v1/households/${hid}/blob`, { baseVersion: 6, envelope: await hc.seal(household, hid, key) })).status, 200);
  assert.deepEqual(db.prepare("SELECT version FROM blobs WHERE hid = ? ORDER BY version").all(hid).map(r => r.version), [7]);
  db.close();
});
// ── S5 — rotation de la clé de foyer après retrait d'un appareil ──
const ecdh = async () => {
  const kp = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
  return { kp, pub: hc.toB64url(new Uint8Array(await crypto.subtle.exportKey("raw", kp.publicKey))) };
};
const hid2 = hc.newHid(), k1 = hc.newKey(), s1 = await hc.joinSecret(k1);
const A2 = await newDevice(), B2 = await newDevice(), C2 = await newDevice();
const [eA, eB, eC] = [await ecdh(), await ecdh(), await ecdh()];
await check("rotation : préparation (A admin, B et C approuvés, clés ECDH enregistrées)", async () => {
  assert.equal((await call(A2, "POST", "/api/v1/households", { hid: hid2, pubkey: A2.pub, joinVerifier: await hc.joinVerifier(s1), ecdhPub: eA.pub })).status, 201);
  assert.equal((await call(B2, "POST", "/api/v1/join", { pubkey: B2.pub, joinSecret: s1, ecdhPub: eB.pub })).status, 202);
  assert.equal((await call(C2, "POST", "/api/v1/join", { pubkey: C2.pub, joinSecret: s1 })).status, 202);
  assert.equal((await call(C2, "PUT", `/api/v1/households/${hid2}/me/ecdh`, { ecdhPub: eC.pub })).status, 200);
  for (const d of [B2, C2]) assert.equal((await call(A2, "POST", `/api/v1/households/${hid2}/devices/${d.id}/approve`)).status, 200);
  assert.equal((await call(A2, "PUT", `/api/v1/households/${hid2}/blob`, { baseVersion: 0, envelope: await hc.seal(household, hid2, k1) })).status, 200);
  const list = await call(A2, "GET", `/api/v1/households/${hid2}/devices`);
  assert.ok(list.body.devices.every(d => d.ecdhPub));
});
const k2 = hc.newKey(), s2 = await hc.joinSecret(k2);
await check("rotation par un non-admin → 403", async () => {
  const r = await call(B2, "POST", `/api/v1/households/${hid2}/rotate`, { epoch: 1, joinVerifier: await hc.joinVerifier(s2), wraps: [], baseVersion: 1, envelope: await hc.seal(household, hid2, k2, 1) });
  assert.equal(r.status, 403);
});
await check("A retire C puis fait tourner la clé (époque 1)", async () => {
  assert.equal((await call(A2, "DELETE", `/api/v1/households/${hid2}/devices/${C2.id}`)).status, 200);
  const wraps = [];
  for (const [d, e] of [[A2, eA], [B2, eB]]) wraps.push({ deviceId: d.id, ...(await hc.wrapKey(eA.kp.privateKey, e.pub, k2, hid2, 1, d.id)) });
  const labelB = JSON.stringify(await hc.seal({ label: "iPhone de Barnabé" }, "hh_libelle_appareil_v1", k2));
  const r = await call(A2, "POST", `/api/v1/households/${hid2}/rotate`, { epoch: 1, joinVerifier: await hc.joinVerifier(s2), wraps,
    labels: [{ deviceId: B2.id, labelCt: labelB }], baseVersion: 1, envelope: await hc.seal(household, hid2, k2, 1) });
  assert.equal(r.status, 200); assert.equal(r.body.epoch, 1); assert.equal(r.body.version, 2);
  const list = await call(A2, "GET", `/api/v1/households/${hid2}/devices`);
  const lb = list.body.devices.find(d => d.deviceId === B2.id).labelCt;
  assert.equal((await hc.open(JSON.parse(lb), k2)).label, "iPhone de Barnabé"); // libellé rescellé, lisible avec la nouvelle clé
});
await check("B envoie avec l'ancienne clé → 409 KEY_ROTATED", async () => {
  const r = await call(B2, "PUT", `/api/v1/households/${hid2}/blob`, { baseVersion: 2, envelope: await hc.seal(household, hid2, k1) });
  assert.equal(r.status, 409); assert.equal(r.body.error, "KEY_ROTATED");
});
await check("B récupère son emballage → nouvelle clé → lit le foyer", async () => {
  const w = await call(B2, "GET", `/api/v1/households/${hid2}/keywrap`);
  assert.equal(w.status, 200); assert.equal(w.body.epoch, 1);
  const key = await hc.unwrapKey(eB.kp.privateKey, w.body.fromEcdhPub, w.body.wrap, hid2, 1, B2.id);
  const blob = await call(B2, "GET", `/api/v1/households/${hid2}/blob`);
  assert.equal(blob.body.envelope.epoch, 1);
  assert.deepEqual(await hc.open(blob.body.envelope, key), household);
  await assert.rejects(() => hc.open(blob.body.envelope, k1)); // l'ancienne clé ne lit plus rien
});
await check("C retiré : plus d'accès ; l'ancien QR ne permet plus de rejoindre", async () => {
  assert.equal((await call(C2, "GET", `/api/v1/households/${hid2}/keywrap`)).status, 403);
  const D = await newDevice();
  assert.equal((await call(D, "POST", "/api/v1/join", { pubkey: D.pub, joinSecret: s1 })).body.error, "JOIN_DENIED");
  assert.equal((await call(D, "POST", "/api/v1/join", { pubkey: D.pub, joinSecret: s2 })).status, 202);
});

// ── C1.5 — Kit de secours (phrase de 12 mots) ──
const phrase = await hc.newRecoveryPhrase();
const rk = await hc.recoveryKeys(phrase.entropy);
const recBody = async (rawKey, epoch) => ({ rid: rk.rid, verifier: await hc.joinVerifier(rk.auth), epoch,
  wrap: await hc.wrapRecovery(rk.kek, rawKey, hid2, epoch) });
const curVersion = async dev => (await call(dev, "GET", `/api/v1/households/${hid2}/blob`)).body.version;
await check("secours : B (non admin) ne peut pas créer le kit ; mauvaise époque refusée", async () => {
  assert.equal((await call(B2, "PUT", `/api/v1/households/${hid2}/recovery`, await recBody(k2, 1))).body.error, "ADMIN_ONLY");
  assert.equal((await call(A2, "PUT", `/api/v1/households/${hid2}/recovery`, await recBody(k1, 0))).body.error, "KEY_ROTATED");
});
await check("secours : A crée le kit → état « configuré, à jour »", async () => {
  assert.equal((await call(A2, "PUT", `/api/v1/households/${hid2}/recovery`, await recBody(k2, 1))).status, 200);
  const st = await call(B2, "GET", `/api/v1/households/${hid2}/recovery`);
  assert.equal(st.body.configured, true); assert.equal(st.body.upToDate, true); assert.equal(st.body.rid, undefined);
});
const N = await newDevice();
await check("secours : mauvaise phrase → 403 RECOVERY_DENIED", async () => {
  const bad = await hc.recoveryKeys((await hc.newRecoveryPhrase()).entropy);
  assert.equal((await call(N, "POST", "/api/v1/recover", { rid: rk.rid, auth: bad.auth, pubkey: N.pub })).body.error, "RECOVERY_DENIED");
  assert.equal((await call(N, "POST", "/api/v1/recover", { rid: bad.rid, auth: bad.auth, pubkey: N.pub })).body.error, "RECOVERY_DENIED");
});
await check("secours : tous les appareils perdus → la phrase seule rend le foyer (nouvel appareil admin)", async () => {
  const ent = await hc.parseRecoveryPhrase(phrase.words.join(" "));
  const keys = await hc.recoveryKeys(ent);
  const r = await call(N, "POST", "/api/v1/recover", { rid: keys.rid, auth: keys.auth, pubkey: N.pub });
  assert.equal(r.status, 200); assert.equal(r.body.hid, hid2); assert.equal(r.body.isAdmin, true);
  const key = await hc.unwrapRecovery(keys.kek, r.body.wrap, hid2, r.body.epoch);
  const blob = await call(N, "GET", `/api/v1/households/${hid2}/blob`);
  assert.deepEqual(await hc.open(blob.body.envelope, key), household);
  assert.equal((await call(N, "GET", `/api/v1/households/${hid2}/me`)).body.isAdmin, true);
});
await check("secours : rotation SANS nouvel emballage → kit périmé (409 RECOVERY_STALE)", async () => {
  const k3 = hc.newKey();
  const r = await call(A2, "POST", `/api/v1/households/${hid2}/rotate`, { epoch: 2, joinVerifier: await hc.joinVerifier(await hc.joinSecret(k3)),
    wraps: [{ deviceId: A2.id, ...(await hc.wrapKey(eA.kp.privateKey, eA.pub, k3, hid2, 2, A2.id)) }],
    baseVersion: await curVersion(A2), envelope: await hc.seal(household, hid2, k3, 2) });
  assert.equal(r.status, 200);
  assert.equal((await call(A2, "GET", `/api/v1/households/${hid2}/recovery`)).body.upToDate, false);
  const Z = await newDevice();
  assert.equal((await call(Z, "POST", "/api/v1/recover", { rid: rk.rid, auth: rk.auth, pubkey: Z.pub })).body.error, "RECOVERY_STALE");
});
await check("secours : rotation AVEC emballage du kit → la phrase donne la NOUVELLE clé", async () => {
  const k4 = hc.newKey();
  const r = await call(A2, "POST", `/api/v1/households/${hid2}/rotate`, { epoch: 3, joinVerifier: await hc.joinVerifier(await hc.joinSecret(k4)),
    wraps: [{ deviceId: A2.id, ...(await hc.wrapKey(eA.kp.privateKey, eA.pub, k4, hid2, 3, A2.id)) }],
    recoveryWrap: await hc.wrapRecovery(rk.kek, k4, hid2, 3),
    baseVersion: await curVersion(A2), envelope: await hc.seal(household, hid2, k4, 3) });
  assert.equal(r.status, 200);
  const Z = await newDevice();
  const rr = await call(Z, "POST", "/api/v1/recover", { rid: rk.rid, auth: rk.auth, pubkey: Z.pub });
  assert.equal(rr.status, 200); assert.equal(rr.body.epoch, 3);
  assert.deepEqual(await hc.unwrapRecovery(rk.kek, rr.body.wrap, hid2, 3), k4);
  await assert.rejects(() => hc.unwrapRecovery(rk.kek, rr.body.wrap, hid2, 2)); // époque liée à l'emballage
});
await check("secours : libellé chiffré de l'appareil récupéré enregistrable", async () => {
  const lc = JSON.stringify({ iv: "aa", ct: "bb" });
  assert.equal((await call(N, "PUT", `/api/v1/households/${hid2}/me/label`, { labelCt: lc })).status, 200);
});
await check("secours : l'admin désactive le kit → la phrase ne marche plus", async () => {
  assert.equal((await call(A2, "DELETE", `/api/v1/households/${hid2}/recovery`)).status, 200);
  const Z = await newDevice();
  assert.equal((await call(Z, "POST", "/api/v1/recover", { rid: rk.rid, auth: rk.auth, pubkey: Z.pub })).body.error, "RECOVERY_DENIED");
  assert.equal((await call(A2, "PUT", `/api/v1/households/${hid2}/recovery`, await (async () => {
    const k = (await call(A2, "GET", `/api/v1/households/${hid2}/me`)).body.epoch; return { ...(await recBody(hc.newKey(), k)) }; })())).status, 200);
});

await check("base serveur aveugle : aucun prénom / allergie / menu / libellé / secret de la phrase en clair", async () => {
  const db = new DatabaseSync(dbPath);
  const dump = JSON.stringify([...["households", "devices", "blobs", "recovery"].flatMap(t => db.prepare(`SELECT * FROM ${t}`).all())]);
  db.close();
  for (const w of ["Zéphyrine", "Barnabé", "peanuts", "d428", "iPhone", "PC de", rk.auth, hc.toB64url(rk.kek), ...phrase.words]) assert.ok(!dump.includes(w), w);
});

server.close();

// ── Phase 2·C — exposition sur Internet : CORS, limites, effacement, purge ──
const APP = "https://rhomark.github.io";
const db2 = join(mkdtempSync(join(tmpdir(), "mij-sync2-")), "sync.db");
const srv2 = createSyncServer({ dbPath: db2, now: () => clock, origins: [APP], trustProxy: true,
  limits: { perMinute: 1000, createPerHour: 3, maxHouseholds: 2 } });
await new Promise(r => srv2.listen(0, "127.0.0.1", r));
const B2URL = `http://127.0.0.1:${srv2.address().port}`;
async function call2(dev, method, path, body, { ip = "203.0.113.1", origin = APP } = {}) {
  const text = body === undefined ? "" : JSON.stringify(body);
  const t = Math.max(clock, dev.lastTs + 1); dev.lastTs = t;
  // Comme le client avec une base ABSOLUE : on signe le chemin de l'URL.
  const url = new URL(B2URL + path);
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, dev.kp.privateKey,
    new TextEncoder().encode(await hc.signingString(method, url.pathname + url.search, t, text))));
  const res = await fetch(url, { method, body: text || undefined, headers: { "Content-Type": "application/json", Origin: origin,
    "X-Forwarded-For": ip, "X-Mij-Device": dev.id, "X-Mij-Ts": String(t), "X-Mij-Sig": hc.toB64url(sig) } });
  return { status: res.status, body: await res.json().catch(() => ({})), headers: res.headers };
}
const newHouse = async (dev, opts) => {
  const h = hc.newHid(), k = hc.newKey();
  const r = await call2(dev, "POST", "/api/v1/households", { hid: h, pubkey: dev.pub, joinVerifier: await hc.joinVerifier(await hc.joinSecret(k)) }, opts);
  return { r, h, k };
};

await check("C2 · /health répond sans authentification ni donnée", async () => {
  const res = await fetch(`${B2URL}/api/v1/health`);
  assert.equal(res.status, 200); assert.deepEqual(await res.json(), { ok: true });
});
await check("C2 · pré-vérification CORS : origine de l'app autorisée, en-têtes X-Mij-* permis", async () => {
  const res = await fetch(`${B2URL}/api/v1/join`, { method: "OPTIONS", headers: { Origin: APP, "Access-Control-Request-Method": "POST" } });
  assert.equal(res.status, 204);
  assert.equal(res.headers.get("access-control-allow-origin"), APP);
  assert.match(res.headers.get("access-control-allow-headers"), /X-Mij-Sig/);
});
await check("C2 · origine inconnue refusée (403 ORIGIN_DENIED)", async () => {
  const res = await fetch(`${B2URL}/api/v1/join`, { method: "OPTIONS", headers: { Origin: "https://evil.example" } });
  assert.equal(res.status, 403);
});
await check("C2 · même origine que l'API acceptée (mijoterie.local), base absolue signée par le chemin", async () => {
  const P = await newDevice();
  const { r } = await newHouse(P, { origin: B2URL, ip: "198.51.100.9" });
  assert.equal(r.status, 201); assert.equal(r.headers.get("access-control-allow-origin"), B2URL);
});
const E = await newDevice();
let eHouse;
await check("C2 · plafond de foyers atteint → 507 CAPACITY", async () => {
  eHouse = await newHouse(E, { ip: "198.51.100.10" });
  assert.equal(eHouse.r.status, 201);
  const third = await newHouse(await newDevice(), { ip: "198.51.100.11" });
  assert.equal(third.r.status, 507); assert.equal(third.r.body.error, "CAPACITY");
});
await check("C2 · limite de créations par IP (429), une autre IP n'est pas bloquée", async () => {
  const X = await newDevice();
  const codes = [];
  for (let i = 0; i < 4; i++) codes.push((await call2(X, "POST", "/api/v1/join", { pubkey: X.pub, joinSecret: hc.toB64url(hc.newKey()) }, { ip: "192.0.2.50" })).status);
  assert.deepEqual(codes, [403, 403, 403, 429]);
  const other = await call2(X, "POST", "/api/v1/join", { pubkey: X.pub, joinSecret: hc.toB64url(hc.newKey()) }, { ip: "192.0.2.51" });
  assert.equal(other.status, 403); // refus normal (mauvais code), pas 429
});
await check("C2 · effacement du foyer : membre refusé, admin accepté, plus rien côté serveur", async () => {
  const s = await hc.joinSecret(eHouse.k);
  const F = await newDevice();
  await call2(F, "POST", "/api/v1/join", { pubkey: F.pub, joinSecret: s }, { ip: "198.51.100.12" });
  await call2(E, "POST", `/api/v1/households/${eHouse.h}/devices/${F.id}/approve`);
  assert.equal((await call2(F, "DELETE", `/api/v1/households/${eHouse.h}`)).body.error, "ADMIN_ONLY");
  await call2(E, "PUT", `/api/v1/households/${eHouse.h}/blob`, { baseVersion: 0, envelope: await hc.seal(household, eHouse.h, eHouse.k) });
  assert.equal((await call2(E, "DELETE", `/api/v1/households/${eHouse.h}`)).status, 200);
  const db = new DatabaseSync(db2);
  for (const t of ["households", "devices", "blobs", "key_wraps"]) assert.equal(db.prepare(`SELECT COUNT(*) AS n FROM ${t} WHERE hid = ?`).get(eHouse.h).n, 0, t);
  db.close();
  assert.equal((await call2(E, "GET", `/api/v1/households/${eHouse.h}/me`)).status, 404);
});
await check("C2 · foyer abandonné (aucun appareil vu depuis 6 mois) purgé, foyer actif gardé", async () => {
  const G = await newDevice();
  const g = await newHouse(G, { ip: "198.51.100.13" }); // place libérée par l'effacement
  assert.equal(g.r.status, 201);
  clock += 181 * 24 * 3600e3;
  const H = await newDevice();
  const hh = await newHouse(H, { ip: "198.51.100.14" });
  assert.equal(hh.r.status, 507); // plafond : 2 foyers (le premier test + G)
  srv2.purgeNow();
  const db = new DatabaseSync(db2);
  assert.equal(db.prepare("SELECT COUNT(*) AS n FROM households").get().n, 0);
  db.close();
  assert.equal((await newHouse(H, { ip: "198.51.100.14" })).r.status, 201);
});
srv2.close();
console.log("━".repeat(28));
if (process.exitCode) { console.error("❌ serveur de sync : échec"); process.exit(1); }
console.log(`✅ serveur de sync : ${ok} vérifications OK`);
