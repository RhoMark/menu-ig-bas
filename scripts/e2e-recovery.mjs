// E2E kit de secours (C1.5) — Firefox headless piloté en WebDriver BiDi.
// Appareil A crée le foyer + le kit ; appareil B (autre profil, autres données)
// récupère le foyer avec la seule phrase, retire A (rotation de clé) ; le kit
// reste à jour et un appareil C récupère encore avec la même phrase.
// Manuel (hors pre-commit, ~2 min) :
//   node --disable-warning=ExperimentalWarning scripts/e2e-recovery.mjs "$PWD" <dossier-captures>
import http from "node:http";
import { readFileSync, existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { join, extname } from "node:path";
import { tmpdir } from "node:os";
import { spawn } from "node:child_process";
const REPO = process.argv[2];
const SP = process.argv[3];
const { createSyncServer } = await import(join(REPO, "sync-server/server.mjs"));

const api = createSyncServer({ dbPath: join(mkdtempSync(join(tmpdir(), "e2e-")), "s.db") });
await new Promise(r => api.listen(0, "127.0.0.1", r));
const API = api.address().port;
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".png": "image/png", ".svg": "image/svg+xml", ".webp": "image/webp", ".jpg": "image/jpeg" };
const web = http.createServer((req, res) => {
  if (req.url === "/__blank") { res.writeHead(200, { "Content-Type": "text/html" }); res.end("<!doctype html><title>x</title>"); return; }
  if (req.url.startsWith("/api/")) {
    const p = http.request({ host: "127.0.0.1", port: API, path: req.url, method: req.method, headers: req.headers }, pr => { res.writeHead(pr.statusCode, pr.headers); pr.pipe(res); });
    req.pipe(p); return;
  }
  const f = join(REPO, decodeURIComponent(req.url.split("?")[0]).replace(/^\/$/, "/index.html"));
  if (!existsSync(f)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "Content-Type": TYPES[extname(f)] || "application/octet-stream" }); res.end(readFileSync(f));
});
await new Promise(r => web.listen(0, "127.0.0.1", r));
const ORIGIN = `http://127.0.0.1:${web.address().port}`;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const opened = [];
let portBase = 9400 + Math.floor(Math.random() * 500);
async function browser() {
  const port = portBase++;
  const prof = mkdtempSync(join(SP, "ffp-"));
  const ff = spawn("firefox", ["--headless", "--no-remote", "--profile", prof, `--remote-debugging-port=${port}`, "--window-size=1100,1400"], { stdio: "ignore" });
  let ws;
  for (let i = 0; i < 60; i++) {
    try { ws = new WebSocket(`ws://127.0.0.1:${port}/session`); await new Promise((ok, ko) => { ws.onopen = ok; ws.onerror = ko; }); break; }
    catch { await sleep(500); }
  }
  let id = 0; const pend = new Map();
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
  const cmd = (method, params) => new Promise((ok, ko) => { const i = ++id; pend.set(i, m => m.type === "error" ? ko(new Error(m.error + ": " + m.message)) : ok(m.result)); ws.send(JSON.stringify({ id: i, method, params })); });
  await cmd("session.new", { capabilities: {} });
  const ctx = (await cmd("browsingContext.getTree", {})).contexts[0].context;
  const ev = async expr => {
    const r = await cmd("script.evaluate", { expression: (globalThis.HELPERS || "") + expr, target: { context: ctx }, awaitPromise: true });
    if (r.type === "exception") throw new Error("JS: " + JSON.stringify(r.exceptionDetails.text));
    return r.result?.value;
  };
  const nav = url => cmd("browsingContext.navigate", { context: ctx, url, wait: "complete" });
  const shot = async name => { const r = await cmd("browsingContext.captureScreenshot", { context: ctx, origin: "document" }); writeFileSync(join(SP, name), Buffer.from(r.data, "base64")); };
  opened.push(ff);
  return { ev, nav, shot, close: async () => { try { await cmd("session.end", {}); } catch {} ff.kill(); } };
}
const helpers = `
window.$btn = t => [...document.querySelectorAll("button")].find(b => b.textContent.includes(t));
window.$click = t => { const b = $btn(t); if (!b) throw new Error("bouton introuvable : " + t); b.click(); return true; };
window.$set = (el, v) => { const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v); el.dispatchEvent(new Event("input", {bubbles: true})); };
window.$text = () => document.body.innerText;
window.$foyer = () => { if (!document.body.innerText.includes("Foyer partagé (labo)")) { const b = [...document.querySelectorAll("button")].find(x => x.textContent.trim() === "Mon foyer"); if (b) b.click(); } return true; };
`;
globalThis.HELPERS = helpers;
async function waitFor(b, expr, label, ms = 30000) {
  for (let t = 0; t < ms; t += 400) { try { await b.ev(helpers + "$foyer()"); if (await b.ev(expr)) return; } catch {} await sleep(400); }
  await b.shot(`e2e-fail-${label}.png`);
  throw new Error("timeout : " + label + " | " + (await b.ev("document.body.innerText.slice(0, 1500)")));
}
const state = (names) => JSON.stringify({ schema: 2,
  users: { u1: { id: "u1", name: "Utilisateur", householdId: "h1", createdAt: "2026-01-01T00:00:00Z" } },
  households: { h1: { id: "h1", members: names.map((n, i) => ({ id: i + 1, name: n, birthYear: 1980 + i, sex: "F", allergies: i === 0 ? ["peanuts"] : [], healthProfile: "healthy" })),
    preferences: { budgetWeekly: 150 }, menus: {}, ratings: {}, pantry: {}, manualItems: {}, journal: {}, favorites: [],
    settings: { onboarded: true, hasSeenTutorial: true, consentedAt: "2026-01-01T00:00:00Z" } } },
  session: { activeUserId: "u1", activeHouseholdId: "h1" } });
async function boot(b, names, tries = 2) {
  try { await boot1(b, names); }
  catch (e) { if (tries > 1) { log("boot : nouvel essai"); return boot(b, names, tries - 1); } throw e; }
}
async function boot1(b, names) {
  await b.nav(ORIGIN + "/__blank");
  await b.ev(`localStorage.clear(); localStorage.setItem("menu-ig-bas-v2", ${JSON.stringify(state(names))}); localStorage.setItem("menu-ig-bas-synclab", "on"); true`);
  await b.nav(ORIGIN + "/index.html?sync=lab");
  await waitFor(b, `!!document.querySelector("nav, aside") && document.body.innerText.includes("Planning")`, "boot", 60000);
  // 1ʳᵉ visite : le SW s'installe puis l'app se recharge une fois → on attend la fin.
  await waitFor(b, `!!navigator.serviceWorker.controller`, "sw", 30000);
  await sleep(2500);
  await waitFor(b, `document.body.innerText.includes("Planning") || document.body.innerText.includes("Mon foyer")`, "boot2", 60000);
  await b.ev(helpers + "true");
  await b.ev(`[...document.querySelectorAll("button")].find(x => x.textContent.trim() === "Mon foyer").click(); true`);
  await waitFor(b, `document.body.innerText.includes("Foyer partagé (labo)")`, "foyer");
}
const log = (...a) => console.log("•", ...a);
let fails = 0;
try {
  // ── Appareil A
  const A = await browser();
  await boot(A, ["Zoé", "Basile"]);
  await waitFor(A, `!!$btn("Créer le foyer partagé")`, "creer");
  await A.ev(`$click("Créer le foyer partagé")`);
  await waitFor(A, `!!$btn("Activer le serveur maison")`, "activer");
  await sleep(1500);
  await waitFor(A, `!!$btn("Activer le serveur maison")`, "activer2");
  await A.ev(`$click("Activer le serveur maison")`);
  await waitFor(A, `document.body.innerText.includes("Serveur maison activé") || !!$btn("Créer le kit de secours")`, "server-on");
  await waitFor(A, `!!$btn("Créer le kit de secours")`, "kit-btn");
  await A.ev(`$click("Créer le kit de secours")`);
  await waitFor(A, `!!$btn("J'ai noté les 12 mots")`, "mots");
  const words = JSON.parse(await A.ev(`JSON.stringify([...document.querySelectorAll("ol.font-mono li")].map(li => li.childNodes[li.childNodes.length - 1].textContent.trim()))`));
  log("phrase", words.length, "mots");
  if (words.length !== 12) throw new Error("12 mots attendus");
  await A.shot("e2e-A-words.png");
  await A.ev(`$click("J'ai noté les 12 mots")`);
  await waitFor(A, `document.body.innerText.includes("recopie deux mots")`, "check");
  // mauvais mots d'abord
  await A.ev(`var ins = [...document.querySelectorAll("label input")].filter(i => i.closest("label").textContent.startsWith("Mot n°")); $set(ins[0], "zzzz"); $set(ins[1], "zzzz"); true`);
  await A.ev(`$click("Activer le kit")`);
  await waitFor(A, `document.body.innerText.includes("Ce ne sont pas les mots")`, "bad-words");
  log("mauvais mots refusés ✓");
  const asks = JSON.parse(await A.ev(`JSON.stringify([...document.querySelectorAll("label")].filter(l => l.textContent.startsWith("Mot n°")).map(l => parseInt(l.textContent.match(/\\d+/)[0])))`));
  await A.ev(`var ins = [...document.querySelectorAll("label input")].filter(i => i.closest("label").textContent.startsWith("Mot n°"));
    $set(ins[0], ${JSON.stringify(words[asks[0] - 1].normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase())}); $set(ins[1], ${JSON.stringify(words[asks[1] - 1].slice(0, 4))}); true`);
  await A.ev(`$click("Activer le kit")`);
  await waitFor(A, `document.body.innerText.includes("Kit de secours activé")`, "kit-on");
  await waitFor(A, `document.body.innerText.includes("Kit de secours actif et à jour")`, "kit-status");
  log("kit activé sur A ✓");
  await sleep(4000); // laisse partir la synchro (syncMeta.recovery dans le foyer chiffré)
  await A.ev(`$click("Synchroniser maintenant"); true`);
  await sleep(3000);
  await A.shot("e2e-A-kit.png");
  await A.close();

  // ── Appareil B : autre profil, autre foyer local, tout A est « perdu »
  const B = await browser();
  await boot(B, ["Inconnu"]);
  await B.ev(`$click("Récupérer avec la phrase de secours")`);
  await waitFor(B, `!!document.querySelector("textarea")`, "textarea");
  // mauvaise phrase (ordre inversé)
  await B.ev(`$set(document.querySelector("textarea"), ${JSON.stringify([words[1], words[0], ...words.slice(2)].join(" "))}); true`);
  await B.ev(`$click("Récupérer le foyer")`);
  await waitFor(B, `/phrase est incorrecte|ne correspond à aucun foyer/.test(document.body.innerText)`, "bad-phrase");
  log("phrase inversée refusée ✓");
  await B.ev(`$set(document.querySelector("textarea"), ${JSON.stringify(words.map((w, i) => `${i + 1}. ${w}`).join("\n"))}); true`);
  await B.ev(`$click("Récupérer le foyer")`);
  await waitFor(B, `document.body.innerText.includes("Foyer retrouvé")`, "recovered");
  await B.shot("e2e-B-who.png");
  await B.ev(`$click("Zoé")`);
  await waitFor(B, `document.body.innerText.includes("Foyer rejoint")`, "joined");
  await waitFor(B, `document.body.innerText.includes("Basile") && !document.body.innerText.includes("Inconnu")`, "members");
  log("B a retrouvé le foyer de A (Zoé, Basile) ✓");
  await waitFor(B, `document.body.innerText.includes("Kit de secours actif et à jour")`, "B-kit-status");
  log("B est admin et voit le kit actif ✓");
  // B retire l'appareil perdu A → rotation de clé → le kit doit rester à jour
  await B.ev(`$click("📱 Appareils")`);
  await waitFor(B, `[...document.querySelectorAll("button")].filter(b => b.textContent.trim() === "Retirer").length >= 1`, "devices");
  await B.ev(`[...document.querySelectorAll("button")].find(b => b.textContent.trim() === "Retirer").click(); true`);
  await waitFor(B, `document.body.innerText.includes("Clé du foyer changée")`, "rotated");
  await B.ev(`$click("Synchroniser maintenant"); true`); await sleep(1500);
  // recharge l'état du kit
  await B.nav(ORIGIN + "/index.html?sync=lab");
  await waitFor(B, `document.body.innerText.includes("Planning")`, "reboot", 60000);
  await B.ev(helpers + `[...document.querySelectorAll("button")].find(x => x.textContent.trim() === "Mon foyer").click(); true`);
  await waitFor(B, `document.body.innerText.includes("Kit de secours actif et à jour")`, "kit-after-rotation");
  log("après rotation (clé n° 1), kit toujours à jour ✓");
  await B.shot("e2e-B-final.png");
  await B.close();

  // ── Appareil C : la même phrase marche encore après la rotation
  const C = await browser();
  await boot(C, ["Autre"]);
  await C.ev(`$click("Récupérer avec la phrase de secours")`);
  await waitFor(C, `!!document.querySelector("textarea")`, "textarea-c");
  await C.ev(`$set(document.querySelector("textarea"), ${JSON.stringify(words.join(" "))}); true`);
  await C.ev(`$click("Récupérer le foyer")`);
  await waitFor(C, `document.body.innerText.includes("Foyer retrouvé")`, "recovered-c");
  log("C récupère encore le foyer avec la même phrase après la rotation ✓");
  await C.close();
} catch (e) { console.error("❌", e.message); fails++; }
for (const ff of opened) { try { ff.kill(); } catch {} }
web.close(); api.close();
console.log(fails ? "❌ E2E échec" : "✅ E2E kit de secours OK");
process.exit(fails ? 1 : 0);
