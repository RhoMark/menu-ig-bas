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

await check("base serveur aveugle : aucun prénom / allergie / menu / libellé en clair", async () => {
  const db = new DatabaseSync(dbPath);
  const dump = JSON.stringify([...["households", "devices", "blobs"].flatMap(t => db.prepare(`SELECT * FROM ${t}`).all())]);
  db.close();
  for (const w of ["Zéphyrine", "Barnabé", "peanuts", "d428", "iPhone", "PC de"]) assert.ok(!dump.includes(w), w);
});

server.close();
console.log("━".repeat(28));
if (process.exitCode) { console.error("❌ serveur de sync : échec"); process.exit(1); }
console.log(`✅ serveur de sync : ${ok} vérifications OK`);
