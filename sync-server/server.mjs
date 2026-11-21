#!/usr/bin/env node
/**
 * Serveur de synchronisation maison « La Mijoterie » — Phase 2·L (S4)
 * ---------------------------------------------------------------------------
 * Serveur AVEUGLE : il ne stocke que
 *   - l'identifiant opaque du foyer (hid, aléatoire),
 *   - l'enveloppe chiffrée du foyer (chiffrée côté appareil, clé de foyer
 *     jamais transmise — INV-1 / INV-2),
 *   - les clés PUBLIQUES des appareils + leur libellé CHIFFRÉ,
 *   - des métadonnées techniques (versions, dates, tailles).
 * Il ne peut lire ni prénoms, ni allergies, ni menus.
 *
 * Zéro dépendance externe : node:http + node:sqlite (intégré à Node 22) +
 * node:crypto. Écoute 127.0.0.1 UNIQUEMENT : seul Caddy (HTTPS, /api/*) le
 * joint ; il n'est jamais exposé directement sur le WiFi.
 * Aucune IP ni identifiant n'est journalisé.
 *
 * Authentification (spec Q-F) : chaque appareil possède une paire ECDSA
 * P-256 ; sa clé privée ne quitte jamais l'appareil. Chaque requête est
 * signée sur « MÉTHODE\nchemin\nhorodatage\nsha256(corps) » (format WebCrypto
 * r||s). Anti-rejeu : horodatage à ±2 min ET strictement croissant par
 * appareil.
 *
 * Règles foyer appliquées ici (décisions HedgeX 2026-10-20) :
 *   - 8 appareils maximum par foyer (en attente compris)       — Q-B
 *   - tout nouvel appareil reste EN ATTENTE jusqu'à approbation
 *     d'un appareil administrateur                             — Q-C / INV-5
 *   - pour demander à rejoindre, il faut présenter le joinSecret
 *     (dérivé de la clé de foyer → donc avoir scanné le QR)
 *   - rétention : dernière version + 2, purge au-delà de 30 j  — Q-G
 *
 * Usage : node --disable-warning=ExperimentalWarning sync-server/server.mjs
 * Env   : MIJOTERIE_SYNC_PORT (8787), MIJOTERIE_SYNC_DB
 *         (~/.local/share/mijoterie/sync.db)
 * Tests : node scripts/test-sync-server.mjs
 */

import http from "node:http";
import { DatabaseSync } from "node:sqlite";
import { createHash, randomBytes, timingSafeEqual, webcrypto } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";

const subtle = webcrypto.subtle;
export const MAX_DEVICES = 8;
export const KEEP_VERSIONS = 3;              // dernière + 2 précédentes
export const RETENTION_MS = 30 * 24 * 3600e3; // 30 jours
export const CLOCK_SKEW_MS = 120e3;           // ±2 min
const MAX_BODY = 2.5 * 1024 * 1024;           // corps HTTP max
const MAX_ENVELOPE = 2 * 1024 * 1024;         // enveloppe foyer max
// Phase 2·C — exposition sur Internet (VPS) : limites anti-abus. Valeurs par
// défaut prudentes, ajustables par variables d'environnement au lancement.
export const DEFAULT_LIMITS = {
  perMinute: 300,            // requêtes / minute / IP (8 appareils derrière une box : ~20/min en usage normal)
  createPerHour: 20,         // créations de foyer + demandes de jonction / heure / IP
  maxHouseholds: 5000,       // foyers au total sur le serveur
  maxTotalBytes: 2 * 1024 ** 3, // 2 Go d'enveloppes chiffrées au total
  abandonMs: 180 * 24 * 3600e3, // foyer sans aucun appareil vu depuis 6 mois → supprimé
};

const sha256 = buf => createHash("sha256").update(buf).digest();
const b64url = buf => Buffer.from(buf).toString("base64url");
const deviceIdOf = rawPub => b64url(sha256(rawPub)).slice(0, 22);

class HttpError extends Error {
  constructor(status, code) { super(code); this.status = status; this.code = code; }
}
const bad = (status, code) => { throw new HttpError(status, code); };

function openDb(path) {
  if (path !== ":memory:") mkdirSync(dirname(path), { recursive: true });
  const db = new DatabaseSync(path);
  db.exec(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS households (
      hid TEXT PRIMARY KEY, join_verifier TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS devices (
      hid TEXT NOT NULL, device_id TEXT NOT NULL, pubkey TEXT NOT NULL, label_ct TEXT,
      is_admin INTEGER NOT NULL DEFAULT 0, approved INTEGER NOT NULL DEFAULT 0,
      created_at INTEGER NOT NULL, last_seen INTEGER, last_ts INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY (hid, device_id));
    CREATE TABLE IF NOT EXISTS blobs (
      hid TEXT NOT NULL, version INTEGER NOT NULL, envelope TEXT NOT NULL,
      byte_size INTEGER NOT NULL, updated_at INTEGER NOT NULL, by_device TEXT NOT NULL,
      PRIMARY KEY (hid, version));
    CREATE TABLE IF NOT EXISTS key_wraps (
      hid TEXT NOT NULL, device_id TEXT NOT NULL, epoch INTEGER NOT NULL, from_device TEXT NOT NULL,
      wrap TEXT NOT NULL, PRIMARY KEY (hid, device_id));
  `);
  // S5 — colonnes ajoutées (bases S4 existantes) : époque de clé + clé ECDH d'appareil.
  for (const sql of ["ALTER TABLE households ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0",
                     "ALTER TABLE devices ADD COLUMN ecdh_pub TEXT"]) {
    try { db.exec(sql); } catch { /* colonne déjà présente */ }
  }
  return db;
}

export function createSyncServer({ dbPath, now = () => Date.now(), origins = [], trustProxy = false, limits = {} } = {}) {
  const db = openDb(dbPath);
  const L = { ...DEFAULT_LIMITS, ...limits };
  const q = {
    household: db.prepare("SELECT * FROM households WHERE hid = ?"),
    householdByVerifier: db.prepare("SELECT * FROM households WHERE join_verifier = ?"),
    insertHousehold: db.prepare("INSERT INTO households (hid, join_verifier, created_at) VALUES (?, ?, ?)"),
    device: db.prepare("SELECT * FROM devices WHERE hid = ? AND device_id = ?"),
    devices: db.prepare("SELECT device_id, label_ct, is_admin, approved, created_at, last_seen, ecdh_pub FROM devices WHERE hid = ? ORDER BY created_at"),
    setEcdh: db.prepare("UPDATE devices SET ecdh_pub = ? WHERE hid = ? AND device_id = ?"),
    setLabel: db.prepare("UPDATE devices SET label_ct = ? WHERE hid = ? AND device_id = ?"),
    rotateHousehold: db.prepare("UPDATE households SET epoch = ?, join_verifier = ? WHERE hid = ?"),
    deleteWraps: db.prepare("DELETE FROM key_wraps WHERE hid = ?"),
    insertWrap: db.prepare("INSERT INTO key_wraps (hid, device_id, epoch, from_device, wrap) VALUES (?, ?, ?, ?, ?)"),
    wrapFor: db.prepare("SELECT * FROM key_wraps WHERE hid = ? AND device_id = ?"),
    countDevices: db.prepare("SELECT COUNT(*) AS n FROM devices WHERE hid = ?"),
    countAdmins: db.prepare("SELECT COUNT(*) AS n FROM devices WHERE hid = ? AND is_admin = 1 AND approved = 1"),
    insertDevice: db.prepare("INSERT INTO devices (hid, device_id, pubkey, label_ct, is_admin, approved, created_at, last_seen, last_ts, ecdh_pub) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"),
    touchDevice: db.prepare("UPDATE devices SET last_ts = ?, last_seen = ? WHERE hid = ? AND device_id = ?"),
    approveDevice: db.prepare("UPDATE devices SET approved = 1 WHERE hid = ? AND device_id = ?"),
    setAdmin: db.prepare("UPDATE devices SET is_admin = ? WHERE hid = ? AND device_id = ?"),
    deleteDevice: db.prepare("DELETE FROM devices WHERE hid = ? AND device_id = ?"),
    latestBlob: db.prepare("SELECT * FROM blobs WHERE hid = ? ORDER BY version DESC LIMIT 1"),
    insertBlob: db.prepare("INSERT INTO blobs (hid, version, envelope, byte_size, updated_at, by_device) VALUES (?, ?, ?, ?, ?, ?)"),
    pruneOld: db.prepare(`DELETE FROM blobs WHERE hid = ? AND version NOT IN
      (SELECT version FROM blobs WHERE hid = ? ORDER BY version DESC LIMIT ?)`),
    pruneExpired: db.prepare(`DELETE FROM blobs WHERE updated_at < ? AND version <
      (SELECT MAX(version) FROM blobs b2 WHERE b2.hid = blobs.hid)`),
    countHouseholds: db.prepare("SELECT COUNT(*) AS n FROM households"),
    totalBytes: db.prepare("SELECT COALESCE(SUM(byte_size), 0) AS n FROM blobs"),
    abandoned: db.prepare(`SELECT hid FROM households WHERE created_at < ?
      AND hid NOT IN (SELECT hid FROM devices WHERE last_seen >= ?)`),
  };
  // Suppression complète d'un foyer (droit à l'effacement, foyers abandonnés).
  const deleteHousehold = hid => {
    db.exec("BEGIN");
    try {
      for (const t of ["key_wraps", "blobs", "devices", "households"]) db.prepare(`DELETE FROM ${t} WHERE hid = ?`).run(hid);
      db.exec("COMMIT");
    } catch (e) { db.exec("ROLLBACK"); throw e; }
  };
  const purgeAbandoned = () => {
    const cutoff = now() - L.abandonMs;
    for (const { hid } of q.abandoned.all(cutoff, cutoff)) deleteHousehold(hid);
  };
  const requireCapacity = (extraBytes = 0) => {
    if (q.totalBytes.get().n + extraBytes > L.maxTotalBytes) bad(507, "CAPACITY");
  };

  // ── Limites de requêtes (mémoire seulement, jamais écrites ni journalisées) ──
  // L'IP n'est gardée que sous forme d'empreinte salée (sel aléatoire par
  // démarrage) le temps de la fenêtre de comptage.
  const salt = randomBytes(16);
  const buckets = new Map(); // empreinte → {min, minCount, hour, hourCount}
  function clientKey(req) {
    let ip = req.socket.remoteAddress || "";
    const loopback = ip === "127.0.0.1" || ip === "::1" || ip === "::ffff:127.0.0.1";
    if (trustProxy && loopback && typeof req.headers["x-forwarded-for"] === "string") {
      ip = req.headers["x-forwarded-for"].split(",").pop().trim(); // ajouté par Caddy = vrai client
    }
    return createHash("sha256").update(salt).update(ip).digest("base64url").slice(0, 16);
  }
  function rateLimit(req, isCreate) {
    const k = clientKey(req), t = now();
    const b = buckets.get(k) || { min: 0, minCount: 0, hour: 0, hourCount: 0 };
    const m = Math.floor(t / 60e3), h = Math.floor(t / 3600e3);
    if (b.min !== m) { b.min = m; b.minCount = 0; }
    if (b.hour !== h) { b.hour = h; b.hourCount = 0; }
    b.minCount++;
    if (isCreate) b.hourCount++;
    buckets.set(k, b);
    if (b.minCount > L.perMinute || (isCreate && b.hourCount > L.createPerHour)) bad(429, "RATE_LIMITED");
  }
  const sweepBuckets = () => { const h = Math.floor(now() / 3600e3); for (const [k, b] of buckets) if (b.hour < h - 1) buckets.delete(k); };

  // ── CORS : l'app publique (autre domaine) appelle l'API ───────────────
  // Autorisé : les origines listées + la même origine que l'API (mijoterie.local).
  function allowedOrigin(req) {
    const o = req.headers.origin;
    if (typeof o !== "string") return null; // pas un navigateur cross-origin (curl, même origine en GET)
    if (origins.includes(o)) return o;
    try { if (new URL(o).host === req.headers.host) return o; } catch { /* origine illisible */ }
    return false;
  }

  // ── Vérification de signature ─────────────────────────────────────────
  async function verifySig(rawPubB64, req, bodyBuf) {
    const ts = Number(req.headers["x-mij-ts"]);
    const sig = req.headers["x-mij-sig"];
    if (!Number.isFinite(ts) || typeof sig !== "string") bad(401, "AUTH_MISSING");
    if (Math.abs(now() - ts) > CLOCK_SKEW_MS) bad(401, "CLOCK_SKEW");
    let key;
    try {
      key = await subtle.importKey("raw", Buffer.from(rawPubB64, "base64url"),
        { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
    } catch { bad(400, "PUBKEY_INVALID"); }
    const msg = `${req.method}\n${req.url}\n${ts}\n${sha256(bodyBuf).toString("hex")}`;
    const ok = await subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key,
      Buffer.from(sig, "base64url"), new TextEncoder().encode(msg));
    if (!ok) bad(401, "BAD_SIGNATURE");
    return ts;
  }
  // Appareil déjà enregistré : signature + anti-rejeu (ts strictement croissant).
  async function authDevice(hid, req, bodyBuf, { requireApproved = true } = {}) {
    const deviceId = req.headers["x-mij-device"];
    const dev = typeof deviceId === "string" ? q.device.get(hid, deviceId) : null;
    if (!dev) bad(403, "UNKNOWN_DEVICE");
    const ts = await verifySig(dev.pubkey, req, bodyBuf);
    if (ts <= dev.last_ts) bad(401, "REPLAY");
    q.touchDevice.run(ts, now(), hid, dev.device_id);
    if (requireApproved && !dev.approved) bad(403, "NOT_APPROVED");
    return dev;
  }
  const requireAdmin = dev => { if (!dev.is_admin) bad(403, "ADMIN_ONLY"); };
  const parseJson = buf => { try { return JSON.parse(buf.toString("utf8") || "{}"); } catch { bad(400, "JSON_INVALID"); } };
  const isHid = s => typeof s === "string" && /^hh_[A-Za-z0-9_-]{16,64}$/.test(s);
  const isB64 = (s, max = 4096) => typeof s === "string" && s.length <= max && /^[A-Za-z0-9_-]+$/.test(s);
  const ecdhOrNull = v => (isB64(v, 200) ? v : null);
  const envEpoch = env => Number(env?.epoch || 0);
  // Enveloppe foyer valide ET de l'époque de clé courante (sinon clé périmée → 409 KEY_ROTATED).
  function checkEnvelope(env, hid, epoch) {
    if (!env || env.format !== "mijoterie-foyer" || env.v !== 1 || env.hid !== hid || !isB64(env.iv, 64) || !isB64(env.ct, MAX_ENVELOPE)
        || !Number.isInteger(envEpoch(env)) || envEpoch(env) < 0) bad(400, "ENVELOPE_INVALID");
    if (envEpoch(env) !== epoch) bad(409, "KEY_ROTATED");
    const text = JSON.stringify({ format: env.format, v: env.v, hid: env.hid, ...(envEpoch(env) ? { epoch: envEpoch(env) } : {}),
      iv: env.iv, ct: env.ct, sealedAt: String(env.sealedAt || "").slice(0, 40) });
    if (text.length > MAX_ENVELOPE) bad(413, "TOO_LARGE");
    return text;
  }

  // ── Routes ────────────────────────────────────────────────────────────
  async function route(req, bodyBuf) {
    const url = new URL(req.url, "http://x");
    const p = url.pathname.split("/").filter(Boolean); // ["api","v1",...]
    if (p[0] !== "api" || p[1] !== "v1") bad(404, "NOT_FOUND");
    const r = p.slice(2);
    const M = req.method;

    // GET /api/v1/health — surveillance (aucune donnée)
    if (M === "GET" && r.length === 1 && r[0] === "health") return [200, { ok: true }];
    rateLimit(req, M === "POST" && r.length === 1 && (r[0] === "households" || r[0] === "join"));

    // POST /api/v1/households — le fondateur crée le foyer (devient admin approuvé)
    if (M === "POST" && r.length === 1 && r[0] === "households") {
      const b = parseJson(bodyBuf);
      if (!isHid(b.hid) || !isB64(b.pubkey, 200) || !/^[0-9a-f]{64}$/.test(b.joinVerifier || "")) bad(400, "FIELDS_INVALID");
      await verifySig(b.pubkey, req, bodyBuf);
      if (q.household.get(b.hid)) bad(409, "HOUSEHOLD_EXISTS");
      if (q.countHouseholds.get().n >= L.maxHouseholds) bad(507, "CAPACITY");
      const deviceId = deviceIdOf(Buffer.from(b.pubkey, "base64url"));
      const t = now();
      db.exec("BEGIN");
      try {
        q.insertHousehold.run(b.hid, b.joinVerifier, t);
        q.insertDevice.run(b.hid, deviceId, b.pubkey, String(b.labelCt || "").slice(0, 4096), 1, 1, t, t, Number(req.headers["x-mij-ts"]), ecdhOrNull(b.ecdhPub));
        db.exec("COMMIT");
      } catch (e) { db.exec("ROLLBACK"); throw e; }
      return [201, { hid: b.hid, deviceId, approved: true, isAdmin: true }];
    }

    // POST /api/v1/join — demande de jonction (prouve la connaissance du QR via joinSecret)
    if (M === "POST" && r.length === 1 && r[0] === "join") {
      const b = parseJson(bodyBuf);
      if (!isB64(b.pubkey, 200) || !isB64(b.joinSecret, 100)) bad(400, "FIELDS_INVALID");
      await verifySig(b.pubkey, req, bodyBuf);
      const verifier = sha256(Buffer.from(b.joinSecret, "base64url")).toString("hex");
      const h = q.householdByVerifier.get(verifier);
      if (!h || !timingSafeEqual(Buffer.from(h.join_verifier), Buffer.from(verifier))) bad(403, "JOIN_DENIED");
      const deviceId = deviceIdOf(Buffer.from(b.pubkey, "base64url"));
      const existing = q.device.get(h.hid, deviceId);
      if (existing) return [200, { hid: h.hid, deviceId, approved: !!existing.approved, isAdmin: !!existing.is_admin }];
      if (q.countDevices.get(h.hid).n >= MAX_DEVICES) bad(409, "DEVICE_LIMIT");
      const t = now();
      q.insertDevice.run(h.hid, deviceId, b.pubkey, String(b.labelCt || "").slice(0, 4096), 0, 0, t, t, Number(req.headers["x-mij-ts"]), ecdhOrNull(b.ecdhPub));
      return [202, { hid: h.hid, deviceId, approved: false, isAdmin: false }];
    }

    if (r[0] !== "households" || !isHid(r[1])) bad(404, "NOT_FOUND");
    const hid = r[1];
    const house = q.household.get(hid);
    if (!house) bad(404, "HOUSEHOLD_UNKNOWN");

    // DELETE /households/:hid — admin : efface TOUT le foyer du serveur (droit à
    // l'effacement). Les données restent sur les appareils.
    if (M === "DELETE" && r.length === 2) {
      requireAdmin(await authDevice(hid, req, bodyBuf));
      deleteHousehold(hid);
      return [200, { ok: true }];
    }
    // GET /households/:hid/me — statut de MON appareil (autorisé même en attente)
    if (M === "GET" && r.length === 3 && r[2] === "me") {
      const dev = await authDevice(hid, req, bodyBuf, { requireApproved: false });
      return [200, { deviceId: dev.device_id, approved: !!dev.approved, isAdmin: !!dev.is_admin, epoch: house.epoch, hasEcdh: !!dev.ecdh_pub,
        adminCount: q.countAdmins.get(hid).n }];
    }
    // PUT /households/:hid/me/ecdh {ecdhPub} — enregistre la clé ECDH de MON appareil (S5, rotation)
    if (M === "PUT" && r.length === 4 && r[2] === "me" && r[3] === "ecdh") {
      const dev = await authDevice(hid, req, bodyBuf, { requireApproved: false });
      const b = parseJson(bodyBuf);
      if (!isB64(b.ecdhPub, 200)) bad(400, "FIELDS_INVALID");
      q.setEcdh.run(b.ecdhPub, hid, dev.device_id);
      return [200, { ok: true }];
    }
    // GET /households/:hid/keywrap — MA nouvelle clé de foyer emballée (après rotation)
    if (M === "GET" && r.length === 3 && r[2] === "keywrap") {
      const dev = await authDevice(hid, req, bodyBuf);
      const w = q.wrapFor.get(hid, dev.device_id);
      if (!w || w.epoch !== house.epoch) bad(404, "NO_WRAP");
      const from = q.device.get(hid, w.from_device);
      if (!from?.ecdh_pub) bad(404, "NO_WRAP");
      return [200, { epoch: w.epoch, from: w.from_device, fromEcdhPub: from.ecdh_pub, wrap: JSON.parse(w.wrap) }];
    }
    // POST /households/:hid/rotate — l'admin change la clé du foyer (après retrait d'un appareil) :
    // nouvelle époque + emballages par appareil + nouveau joinVerifier (anciens QR invalides) + foyer rescellé, d'un bloc.
    if (M === "POST" && r.length === 3 && r[2] === "rotate") {
      const dev = await authDevice(hid, req, bodyBuf);
      requireAdmin(dev);
      const b = parseJson(bodyBuf);
      const epoch = house.epoch + 1;
      if (Number(b.epoch) !== epoch || !/^[0-9a-f]{64}$/.test(b.joinVerifier || "") || !Array.isArray(b.wraps)) bad(400, "FIELDS_INVALID");
      const envText = checkEnvelope(b.envelope, hid, epoch);
      const last = q.latestBlob.get(hid);
      const current = last ? last.version : 0;
      if (Number(b.baseVersion) !== current) bad(409, "CONFLICT");
      if (!b.wraps.some(w => w.deviceId === dev.device_id)) bad(400, "WRAP_SELF_MISSING");
      const t = now();
      db.exec("BEGIN");
      try {
        q.rotateHousehold.run(epoch, b.joinVerifier, hid);
        q.deleteWraps.run(hid);
        for (const w of b.wraps.slice(0, MAX_DEVICES)) {
          if (!q.device.get(hid, w.deviceId) || !isB64(w.iv, 64) || !isB64(w.ct, 200)) continue;
          q.insertWrap.run(hid, w.deviceId, epoch, dev.device_id, JSON.stringify({ iv: w.iv, ct: w.ct }));
        }
        // Libellés d'appareils rescellés par l'admin avec la nouvelle clé (toujours chiffrés).
        for (const l of (Array.isArray(b.labels) ? b.labels : []).slice(0, MAX_DEVICES)) {
          if (typeof l?.labelCt === "string" && l.labelCt.length <= 4096) q.setLabel.run(l.labelCt, hid, String(l.deviceId));
        }
        q.insertBlob.run(hid, current + 1, envText, envText.length, t, dev.device_id);
        q.pruneOld.run(hid, hid, KEEP_VERSIONS);
        db.exec("COMMIT");
      } catch (e) { db.exec("ROLLBACK"); throw e; }
      return [200, { version: current + 1, epoch }];
    }
    // GET /households/:hid/devices — liste (appareil approuvé)
    if (M === "GET" && r.length === 3 && r[2] === "devices") {
      await authDevice(hid, req, bodyBuf);
      const list = q.devices.all(hid).map(d => ({ deviceId: d.device_id, labelCt: d.label_ct, isAdmin: !!d.is_admin,
        approved: !!d.approved, createdAt: d.created_at, lastSeen: d.last_seen, ecdhPub: d.ecdh_pub || null }));
      return [200, { devices: list, max: MAX_DEVICES, epoch: house.epoch }];
    }
    // POST /households/:hid/devices/:id/approve — admin seulement
    if (M === "POST" && r.length === 5 && r[2] === "devices" && r[4] === "approve") {
      requireAdmin(await authDevice(hid, req, bodyBuf));
      if (!q.device.get(hid, r[3])) bad(404, "DEVICE_UNKNOWN");
      q.approveDevice.run(hid, r[3]);
      return [200, { ok: true }];
    }
    // POST /households/:hid/devices/:id/admin {isAdmin} — admin seulement (S6) : un 2ᵉ appareil
    // administrateur évite qu'un navigateur effacé bloque toute approbation.
    if (M === "POST" && r.length === 5 && r[2] === "devices" && r[4] === "admin") {
      requireAdmin(await authDevice(hid, req, bodyBuf));
      const b = parseJson(bodyBuf);
      if (typeof b.isAdmin !== "boolean") bad(400, "FIELDS_INVALID");
      const target = q.device.get(hid, r[3]);
      if (!target) bad(404, "DEVICE_UNKNOWN");
      if (b.isAdmin && !target.approved) bad(409, "TARGET_NOT_APPROVED");
      if (!b.isAdmin && target.is_admin && q.countAdmins.get(hid).n <= 1) bad(409, "LAST_ADMIN");
      q.setAdmin.run(b.isAdmin ? 1 : 0, hid, r[3]);
      return [200, { ok: true }];
    }
    // DELETE /households/:hid/devices/:id — admin (ou l'appareil lui-même)
    if (M === "DELETE" && r.length === 4 && r[2] === "devices") {
      const dev = await authDevice(hid, req, bodyBuf, { requireApproved: false });
      if (dev.device_id !== r[3]) requireAdmin(dev);
      const target = q.device.get(hid, r[3]);
      if (!target) bad(404, "DEVICE_UNKNOWN");
      if (target.is_admin && target.approved && q.countAdmins.get(hid).n <= 1) bad(409, "LAST_ADMIN");
      q.deleteDevice.run(hid, r[3]);
      return [200, { ok: true }];
    }
    // GET /households/:hid/blob?since=N — dernière version (appareil approuvé)
    if (M === "GET" && r.length === 3 && r[2] === "blob") {
      await authDevice(hid, req, bodyBuf);
      const last = q.latestBlob.get(hid);
      if (!last) return [200, { version: 0, envelope: null }];
      const since = Number(url.searchParams.get("since"));
      if (Number.isFinite(since) && since >= last.version) return [200, { version: last.version, epoch: house.epoch, unchanged: true }];
      return [200, { version: last.version, epoch: house.epoch, envelope: JSON.parse(last.envelope), updatedAt: last.updated_at, byDevice: last.by_device }];
    }
    // PUT /households/:hid/blob {baseVersion, envelope} — écriture optimiste
    if (M === "PUT" && r.length === 3 && r[2] === "blob") {
      const dev = await authDevice(hid, req, bodyBuf);
      const b = parseJson(bodyBuf);
      const envText = checkEnvelope(b.envelope, hid, house.epoch);
      requireCapacity(envText.length);
      const last = q.latestBlob.get(hid);
      const current = last ? last.version : 0;
      if (Number(b.baseVersion) !== current) bad(409, "CONFLICT");
      const version = current + 1, t = now();
      q.insertBlob.run(hid, version, envText, envText.length, t, dev.device_id);
      q.pruneOld.run(hid, hid, KEEP_VERSIONS);
      q.pruneExpired.run(t - RETENTION_MS);
      return [200, { version }];
    }
    bad(404, "NOT_FOUND");
  }

  const server = http.createServer((req, res) => {
    const origin = allowedOrigin(req);
    if (origin === false) { send(res, 403, { error: "ORIGIN_DENIED" }); req.resume(); return; }
    if (origin) {
      res.setHeader("Access-Control-Allow-Origin", origin);
      res.setHeader("Vary", "Origin");
    }
    if (req.method === "OPTIONS") { // pré-vérification CORS du navigateur
      res.writeHead(204, origin ? {
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
        "Access-Control-Allow-Headers": "Content-Type, X-Mij-Device, X-Mij-Ts, X-Mij-Sig",
        "Access-Control-Max-Age": "600" } : {});
      res.end(); req.resume(); return;
    }
    const chunks = []; let size = 0, aborted = false;
    req.on("data", c => {
      size += c.length;
      if (size > MAX_BODY && !aborted) { aborted = true; send(res, 413, { error: "TOO_LARGE" }); req.destroy(); }
      else chunks.push(c);
    });
    req.on("end", async () => {
      if (aborted) return;
      try {
        const [status, body] = await route(req, Buffer.concat(chunks));
        send(res, status, body);
      } catch (e) {
        if (e instanceof HttpError) send(res, e.status, { error: e.code });
        else { console.error("[sync] erreur interne :", e.message); send(res, 500, { error: "INTERNAL" }); }
      }
    });
  });
  const purgeTimer = setInterval(() => {
    try { q.pruneExpired.run(now() - RETENTION_MS); purgeAbandoned(); sweepBuckets(); } catch { /* noop */ }
  }, 3600e3);
  server.purgeNow = () => { q.pruneExpired.run(now() - RETENTION_MS); purgeAbandoned(); }; // tests
  purgeTimer.unref();
  server.on("close", () => { clearInterval(purgeTimer); db.close(); });
  return server;
}

function send(res, status, body) {
  const txt = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff", "Content-Length": Buffer.byteLength(txt) });
  res.end(txt);
}

// Lancement direct (pas lors d'un import par les tests)
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const port = Number(process.env.MIJOTERIE_SYNC_PORT || 8787);
  const dbPath = process.env.MIJOTERIE_SYNC_DB || join(homedir(), ".local/share/mijoterie/sync.db");
  // Phase 2·C : MIJOTERIE_SYNC_ORIGINS="https://rhomark.github.io" (séparées par des virgules),
  // MIJOTERIE_SYNC_TRUST_PROXY=1 derrière Caddy (IP du client lue dans X-Forwarded-For).
  const origins = (process.env.MIJOTERIE_SYNC_ORIGINS || "").split(",").map(s => s.trim()).filter(Boolean);
  const trustProxy = process.env.MIJOTERIE_SYNC_TRUST_PROXY === "1";
  const limits = {};
  for (const [k, env] of [["perMinute", "MIJOTERIE_SYNC_PER_MINUTE"], ["createPerHour", "MIJOTERIE_SYNC_CREATE_PER_HOUR"],
                          ["maxHouseholds", "MIJOTERIE_SYNC_MAX_HOUSEHOLDS"], ["maxTotalBytes", "MIJOTERIE_SYNC_MAX_BYTES"]]) {
    if (process.env[env]) limits[k] = Number(process.env[env]);
  }
  createSyncServer({ dbPath, origins, trustProxy, limits }).listen(port, "127.0.0.1", () =>
    console.log(`[sync] La Mijoterie — serveur aveugle sur 127.0.0.1:${port}`));
}
