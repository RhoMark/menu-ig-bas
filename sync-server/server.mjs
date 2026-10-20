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
import { createHash, timingSafeEqual, webcrypto } from "node:crypto";
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
  `);
  return db;
}

export function createSyncServer({ dbPath, now = () => Date.now() } = {}) {
  const db = openDb(dbPath);
  const q = {
    household: db.prepare("SELECT * FROM households WHERE hid = ?"),
    householdByVerifier: db.prepare("SELECT * FROM households WHERE join_verifier = ?"),
    insertHousehold: db.prepare("INSERT INTO households (hid, join_verifier, created_at) VALUES (?, ?, ?)"),
    device: db.prepare("SELECT * FROM devices WHERE hid = ? AND device_id = ?"),
    devices: db.prepare("SELECT device_id, label_ct, is_admin, approved, created_at, last_seen FROM devices WHERE hid = ? ORDER BY created_at"),
    countDevices: db.prepare("SELECT COUNT(*) AS n FROM devices WHERE hid = ?"),
    countAdmins: db.prepare("SELECT COUNT(*) AS n FROM devices WHERE hid = ? AND is_admin = 1 AND approved = 1"),
    insertDevice: db.prepare("INSERT INTO devices (hid, device_id, pubkey, label_ct, is_admin, approved, created_at, last_seen, last_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"),
    touchDevice: db.prepare("UPDATE devices SET last_ts = ?, last_seen = ? WHERE hid = ? AND device_id = ?"),
    approveDevice: db.prepare("UPDATE devices SET approved = 1 WHERE hid = ? AND device_id = ?"),
    deleteDevice: db.prepare("DELETE FROM devices WHERE hid = ? AND device_id = ?"),
    latestBlob: db.prepare("SELECT * FROM blobs WHERE hid = ? ORDER BY version DESC LIMIT 1"),
    insertBlob: db.prepare("INSERT INTO blobs (hid, version, envelope, byte_size, updated_at, by_device) VALUES (?, ?, ?, ?, ?, ?)"),
    pruneOld: db.prepare(`DELETE FROM blobs WHERE hid = ? AND version NOT IN
      (SELECT version FROM blobs WHERE hid = ? ORDER BY version DESC LIMIT ?)`),
    pruneExpired: db.prepare(`DELETE FROM blobs WHERE updated_at < ? AND version <
      (SELECT MAX(version) FROM blobs b2 WHERE b2.hid = blobs.hid)`),
  };

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

  // ── Routes ────────────────────────────────────────────────────────────
  async function route(req, bodyBuf) {
    const url = new URL(req.url, "http://x");
    const p = url.pathname.split("/").filter(Boolean); // ["api","v1",...]
    if (p[0] !== "api" || p[1] !== "v1") bad(404, "NOT_FOUND");
    const r = p.slice(2);
    const M = req.method;

    // POST /api/v1/households — le fondateur crée le foyer (devient admin approuvé)
    if (M === "POST" && r.length === 1 && r[0] === "households") {
      const b = parseJson(bodyBuf);
      if (!isHid(b.hid) || !isB64(b.pubkey, 200) || !/^[0-9a-f]{64}$/.test(b.joinVerifier || "")) bad(400, "FIELDS_INVALID");
      await verifySig(b.pubkey, req, bodyBuf);
      if (q.household.get(b.hid)) bad(409, "HOUSEHOLD_EXISTS");
      const deviceId = deviceIdOf(Buffer.from(b.pubkey, "base64url"));
      const t = now();
      db.exec("BEGIN");
      try {
        q.insertHousehold.run(b.hid, b.joinVerifier, t);
        q.insertDevice.run(b.hid, deviceId, b.pubkey, String(b.labelCt || "").slice(0, 4096), 1, 1, t, t, Number(req.headers["x-mij-ts"]));
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
      q.insertDevice.run(h.hid, deviceId, b.pubkey, String(b.labelCt || "").slice(0, 4096), 0, 0, t, t, Number(req.headers["x-mij-ts"]));
      return [202, { hid: h.hid, deviceId, approved: false, isAdmin: false }];
    }

    if (r[0] !== "households" || !isHid(r[1])) bad(404, "NOT_FOUND");
    const hid = r[1];
    if (!q.household.get(hid)) bad(404, "HOUSEHOLD_UNKNOWN");

    // GET /households/:hid/me — statut de MON appareil (autorisé même en attente)
    if (M === "GET" && r.length === 3 && r[2] === "me") {
      const dev = await authDevice(hid, req, bodyBuf, { requireApproved: false });
      return [200, { deviceId: dev.device_id, approved: !!dev.approved, isAdmin: !!dev.is_admin }];
    }
    // GET /households/:hid/devices — liste (appareil approuvé)
    if (M === "GET" && r.length === 3 && r[2] === "devices") {
      await authDevice(hid, req, bodyBuf);
      const list = q.devices.all(hid).map(d => ({ deviceId: d.device_id, labelCt: d.label_ct, isAdmin: !!d.is_admin,
        approved: !!d.approved, createdAt: d.created_at, lastSeen: d.last_seen }));
      return [200, { devices: list, max: MAX_DEVICES }];
    }
    // POST /households/:hid/devices/:id/approve — admin seulement
    if (M === "POST" && r.length === 5 && r[2] === "devices" && r[4] === "approve") {
      requireAdmin(await authDevice(hid, req, bodyBuf));
      if (!q.device.get(hid, r[3])) bad(404, "DEVICE_UNKNOWN");
      q.approveDevice.run(hid, r[3]);
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
      if (Number.isFinite(since) && since >= last.version) return [200, { version: last.version, unchanged: true }];
      return [200, { version: last.version, envelope: JSON.parse(last.envelope), updatedAt: last.updated_at, byDevice: last.by_device }];
    }
    // PUT /households/:hid/blob {baseVersion, envelope} — écriture optimiste
    if (M === "PUT" && r.length === 3 && r[2] === "blob") {
      const dev = await authDevice(hid, req, bodyBuf);
      const b = parseJson(bodyBuf);
      const env = b.envelope;
      if (!env || env.format !== "mijoterie-foyer" || env.v !== 1 || env.hid !== hid || !isB64(env.iv, 64) || !isB64(env.ct, MAX_ENVELOPE)) bad(400, "ENVELOPE_INVALID");
      const envText = JSON.stringify({ format: env.format, v: env.v, hid: env.hid, iv: env.iv, ct: env.ct, sealedAt: String(env.sealedAt || "").slice(0, 40) });
      if (envText.length > MAX_ENVELOPE) bad(413, "TOO_LARGE");
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
  const purgeTimer = setInterval(() => { try { q.pruneExpired.run(now() - RETENTION_MS); } catch { /* noop */ } }, 3600e3);
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
  createSyncServer({ dbPath }).listen(port, "127.0.0.1", () =>
    console.log(`[sync] La Mijoterie — serveur aveugle sur 127.0.0.1:${port}`));
}
