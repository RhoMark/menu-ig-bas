#!/usr/bin/env node
/**
 * Sauvegarde quotidienne de la base du serveur de synchro (Phase 2·C).
 * Copie cohérente via « VACUUM INTO » (base en service, WAL compris), garde
 * les 7 dernières. Le contenu est déjà chiffré par les appareils : la
 * sauvegarde ne contient que des données illisibles pour le serveur.
 *
 * Env : MIJOTERIE_SYNC_DB (base), MIJOTERIE_SYNC_BACKUP_DIR (dossier), KEEP (7)
 */
import { DatabaseSync } from "node:sqlite";
import { readdirSync, rmSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const dbPath = process.env.MIJOTERIE_SYNC_DB || "/var/lib/mijoterie-sync/sync.db";
const dir = process.env.MIJOTERIE_SYNC_BACKUP_DIR || "/var/backups/mijoterie-sync";
const keep = Number(process.env.KEEP || 7);

mkdirSync(dir, { recursive: true });
const name = `sync-${new Date().toISOString().slice(0, 10)}.db`;
const target = join(dir, name);
rmSync(target, { force: true }); // relance le même jour : on remplace
const db = new DatabaseSync(dbPath, { readOnly: true });
db.exec(`VACUUM INTO '${target.replace(/'/g, "''")}'`);
db.close();

const old = readdirSync(dir).filter(f => /^sync-\d{4}-\d{2}-\d{2}\.db$/.test(f)).sort().slice(0, -keep);
for (const f of old) rmSync(join(dir, f));
console.log(`[backup] ${name} écrit, ${old.length} ancienne(s) supprimée(s)`);
