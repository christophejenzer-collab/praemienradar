"use strict";
/* Prämienradar – rechnet komplett im Browser mit den vorbereiteten BAG-Daten (docs/data). */

const MODELL = { B: "Standard", P: "Hausarzt/HMO", T: "Telmed/andere" };
const FR_ERW = [300, 500, 1000, 1500, 2000, 2500];
const FR_KIN = [0, 100, 200, 300, 400, 500, 600];
const PROGNOSE_JAHRE = 3;

const $ = (id) => document.getElementById(id);
const chf = (x, d = 0) => "CHF " + x.toLocaleString("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let META, PLZ;
const regionCache = {};
let letztesErgebnis = null;

async function json(pfad) {
  const r = await fetch(pfad);
  if (!r.ok) throw new Error(`${pfad}: ${r.status}`);
  return r.json();
}

/* ---------- Formular ---------- */
function franchisenSetzen() {
  const kind = Number($("alter").value) <= 18;
  const liste = kind ? FR_KIN : FR_ERW;
  const sel = $("franchise");
  const alt = Number(sel.value);
  sel.innerHTML = liste.map((f) => `<option value="${f}">${f.toLocaleString("de-CH")}er</option>`).join("");
  sel.value = liste.includes(alt) ? alt : liste[0];
}

function orteSetzen() {
  const orte = PLZ[$("plz").value.trim()] || [];
  const wahl = $("ort-wahl");
  $("ort").innerHTML = orte.map((o, i) => `<option value="${i}">${esc(o[0])}</option>`).join("");
  wahl.hidden = orte.length < 2;
}

function kassenSetzen() {
  const aktiv = META.aktiv || Object.keys(META.kassen);
  const opts = aktiv.map((nr) => [nr, META.kassen[nr]]).sort((a, b) => a[1].localeCompare(b[1], "de"));
  $("kasse").innerHTML = `<option value="">keiner bestimmten Kasse</option>` +
    opts.map(([nr, n]) => `<option value="${nr}">${esc(n)}</option>`).join("");
}

function formularLesen() {
  return {
    plz: $("plz").value.trim(),
    ort: Number($("ort").value || 0),
    alter: Number($("alter").value),
    franchise: Number($("franchise").value),
    unfall: $("unfall").value,
    kasse: $("kasse").value,
    kasseModell: $("kasse-modell").value,
    vergleich: $("vergleich").value,
  };
}

function urlSchreiben(f) {
  const q = new URLSearchParams({ plz: f.plz, alter: f.alter, fr: f.franchise, u: f.unfall, m: f.kasseModell, v: f.vergleich });
  if (f.kasse) q.set("k", f.kasse);
  if (f.ort) q.set("o", f.ort);
  history.replaceState(null, "", "?" + q.toString());
}

function urlLesen() {
  const q = new URLSearchParams(location.search);
  if (!q.get("plz")) return false;
  $("plz").value = q.get("plz");
  if (q.get("alter")) $("alter").value = q.get("alter");
  franchisenSetzen();
  if (q.get("fr")) $("franchise").value = q.get("fr");
  if (q.get("u")) $("unfall").value = q.get("u");
  if (q.get("k")) $("kasse").value = q.get("k");
  if (q.get("m")) $("kasse-modell").value = q.get("m");
  if (q.get("v")) $("vergleich").value = q.get("v");
  orteSetzen();
  if (q.get("o")) $("ort").value = q.get("o");
  return true;
}

function fehler(text) {
  $("fehler").textContent = text;
  $("fehler").hidden = !text;
}

/* ---------- Rechnen ---------- */
function rechnen(datei, f, bfs) {
  const daten = datei.d, gebiete = datei.e || [];
  const erhaeltlich = (r) => r.length < 4 || gebiete[r[3]].includes(bfs);
  const akl = f.alter <= 18 ? "K" : f.alter <= 25 ? "J" : "E";
  const key = `${akl}|${f.unfall}|${f.franchise}`;
  const typ = f.vergleich === "gleich" ? f.kasseModell : null;
  const jahre = Object.keys(daten).map(Number).sort((a, b) => a - b);

  const verlauf = [];
  for (const j of jahre) {
    const liste = (daten[j][key] || []).filter(erhaeltlich);
    const pool = typ ? liste.filter((r) => r[1] === typ) : liste;
    if (!pool.length) continue;
    const best = pool.reduce((a, b) => (b[2] < a[2] ? b : a));
    const eigen = f.kasse ? liste.filter((r) => r[0] === f.kasse && r[1] === f.kasseModell).sort((a, b) => a[2] - b[2])[0] : null;
    verlauf.push({ jahr: j, best, eigen: eigen ? eigen[2] : null });
  }
  if (!verlauf.length) return null;

  const aktuell = verlauf[verlauf.length - 1];
  const liste = (daten[aktuell.jahr][key] || []).filter(erhaeltlich);
  const pool = typ ? liste.filter((r) => r[1] === typ) : liste;
  const proKasse = new Map();
  for (const r of [...pool].sort((a, b) => a[2] - b[2])) if (!proKasse.has(r[0])) proKasse.set(r[0], r);
  const rang = [...proKasse.values()];

  let prognose = [];
  const mitEigen = verlauf.filter((v) => v.eigen != null);
  if (f.kasse && mitEigen.length >= 3) {
    const a = mitEigen[0], z = mitEigen[mitEigen.length - 1], n = z.jahr - a.jahr;
    const wB = Math.pow(z.best[2] / a.best[2], 1 / n) - 1;
    const wE = Math.pow(z.eigen / a.eigen, 1 / n) - 1;
    for (let k = 1; k <= PROGNOSE_JAHRE; k++) {
      prognose.push({ jahr: z.jahr + k, best: z.best[2] * (1 + wB) ** k, eigen: z.eigen * (1 + wE) ** k });
    }
    prognose.wachstum = { best: wB, eigen: wE };
  }
  return { verlauf, aktuell, rang, prognose, typ };
}

/* ---------- Darstellen ---------- */
function anzeigen(e, f) {
  const name = (nr) => META.kassen[nr] || `BAG-Nr. ${nr}`;
  const akt = e.aktuell;
  const diffJahr = akt.eigen != null ? (akt.eigen - akt.best[2]) * 12 : null;

  const zahl = $("fazit-zahl"), text = $("fazit-text");
  zahl.classList.remove("gut");
  if (f.kasse && akt.eigen == null) {
    zahl.textContent = chf(akt.best[2], 2);
    text.textContent = `${name(f.kasse)} bietet das Modell ${MODELL[f.kasseModell]} mit diesen Angaben ${akt.jahr} nicht an. Die günstigste Kasse kostet ${chf(akt.best[2], 2)} pro Monat.`;
  } else if (f.kasse && diffJahr > 0.5) {
    zahl.textContent = chf(diffJahr);
    text.textContent = `So viel sparst du ${akt.jahr} pro Jahr, wenn du von ${name(f.kasse)} zu ${name(akt.best[0])} (${MODELL[akt.best[1]]}) wechselst.`;
  } else if (f.kasse) {
    zahl.textContent = "Bestwert";
    zahl.classList.add("gut");
    text.textContent = `${name(f.kasse)} ist ${akt.jahr} mit diesen Angaben bereits die günstigste Kasse.`;
  } else {
    zahl.textContent = chf(akt.best[2], 2);
    text.textContent = `So viel kostet die günstigste Grundversicherung ${akt.jahr} pro Monat: ${name(akt.best[0])}, Modell ${MODELL[akt.best[1]]}.`;
  }

  // Summen
  const s = [];
  if (f.kasse) {
    const vorjahre = e.verlauf.filter((v) => v.jahr < akt.jahr && v.eigen != null);
    const verpasst = vorjahre.reduce((t, v) => t + Math.max(0, v.eigen - v.best[2]) * 12, 0);
    if (vorjahre.length) s.push([`Mögliche Ersparnis ${vorjahre[0].jahr}–${akt.jahr - 1}`, chf(verpasst)]);
    if (diffJahr != null) s.push([`Ersparnis ${akt.jahr}`, chf(Math.max(0, diffJahr))]);
    if (e.prognose.length) {
      const p = e.prognose.reduce((t, v) => t + Math.max(0, v.eigen - v.best) * 12, 0);
      s.push([`Schätzung ${e.prognose[0].jahr}–${e.prognose.at(-1).jahr}`, chf(p)]);
    }
  } else {
    const teuer = e.rang.at(-1);
    s.push([`Günstigste ${akt.jahr}`, chf(akt.best[2], 2) + " / Mt."]);
    s.push([`Teuerste ${akt.jahr}`, chf(teuer[2], 2) + " / Mt."]);
    s.push(["Spanne pro Jahr", chf((teuer[2] - akt.best[2]) * 12)]);
  }
  $("summen").innerHTML = s.map(([t, w]) => `<div><dt>${esc(t)}</dt><dd>${esc(w)}</dd></div>`).join("");

  // Rangliste
  const top = e.rang.slice(0, 10);
  const eigenPos = e.rang.findIndex((r) => r[0] === f.kasse);
  const zeilen = top.map((r, i) => [i + 1, r]);
  if (eigenPos >= 10) zeilen.push([eigenPos + 1, e.rang[eigenPos]]);
  $("rang-titel").textContent = `Die günstigsten Kassen ${akt.jahr}` + (e.typ ? ` im Modell ${MODELL[e.typ]}` : "");
  $("rang").innerHTML = zeilen.map(([pos, r]) => `
    <tr class="${r[0] === f.kasse ? "eigen" : ""}">
      <td>${pos}</td><td>${esc(name(r[0]))}${r[0] === f.kasse ? (r[1] === f.kasseModell ? " (deine Kasse)" : " (deine Kasse, anderes Modell)") : ""}</td>
      <td>${MODELL[r[1]]}</td><td class="zahl">${r[2].toFixed(2)}</td><td class="zahl jahr-spalte">${(r[2] * 12).toLocaleString("de-CH", { maximumFractionDigits: 0 })}</td>
    </tr>`).join("");

  // Jahrestabelle
  $("jahre").innerHTML = [...e.verlauf].reverse().map((v) => `
    <tr><td>${v.jahr}</td><td>${esc(name(v.best[0]))} (${MODELL[v.best[1]]})</td>
      <td class="zahl">${v.best[2].toFixed(2)}</td>
      <td class="zahl">${v.eigen != null ? v.eigen.toFixed(2) : "–"}</td>
      <td class="zahl">${v.eigen != null ? Math.round((v.eigen - v.best[2]) * 12).toLocaleString("de-CH") : "–"}</td></tr>`).join("");

  $("resultat").hidden = false;
  zeichnen(e, true);
}

function zeichnen(e, neu) {
  const svg = $("chart");
  const W = Math.max(300, svg.parentElement.clientWidth);
  const H = W < 520 ? 250 : 340;
  const rand = { l: W < 520 ? 40 : 56, r: W < 520 ? 22 : 28, o: 22, u: 30 };

  const punkte = [
    ...e.verlauf.map((v) => ({ jahr: v.jahr, best: v.best[2], eigen: v.eigen, prog: false })),
    ...e.prognose.map((v) => ({ ...v, prog: true })),
  ];
  const werte = punkte.flatMap((p) => [p.best, p.eigen]).filter((x) => x != null);
  let lo = Math.min(...werte), hi = Math.max(...werte);
  const pad = (hi - lo) * 0.15 || hi * 0.1;
  lo = Math.max(0, lo - pad * 2); hi += pad;

  const x = (i) => rand.l + (i * (W - rand.l - rand.r)) / Math.max(1, punkte.length - 1);
  const y = (v) => rand.o + (1 - (v - lo) / (hi - lo)) * (H - rand.o - rand.u);
  const pfad = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");

  const nAkt = e.verlauf.length;
  const best = punkte.map((p, i) => [x(i), y(p.best)]);
  const hatEigen = punkte.some((p) => p.eigen != null);
  const eigen = punkte.map((p, i) => (p.eigen != null ? [x(i), y(p.eigen)] : null));

  let s = `<defs><pattern id="schraffur" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="6" height="6" fill="var(--enzian-hell)"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--enzian)" stroke-width="1.2" opacity=".5"/></pattern></defs>`;

  // Raster
  const schritte = 4;
  for (let k = 0; k <= schritte; k++) {
    const v = lo + ((hi - lo) * k) / schritte, yy = y(v);
    s += `<line class="raster" x1="${rand.l}" x2="${W - rand.r}" y1="${yy}" y2="${yy}"/>`;
    s += `<text class="achse" x="${rand.l - 8}" y="${yy + 4}" text-anchor="end">${Math.round(v)}</text>`;
  }
  const jede = W < 520 && punkte.length > 7 ? 2 : 1;
  punkte.forEach((p, i) => {
    if ((punkte.length - 1 - i) % jede === 0)
      s += `<text class="achse" x="${x(i)}" y="${H - 8}" text-anchor="middle">${p.jahr}</text>`;
  });

  // Berg unter der günstigsten Linie
  s += `<path class="berg" d="${pfad(best)}L${best.at(-1)[0]},${H - rand.u}L${best[0][0]},${H - rand.u}Z"/>`;

  // Lücke (Ersparnis) – Ist-Jahre und Prognose getrennt
  if (hatEigen) {
    const flaeche = (von, bis, cls) => {
      const idx = [];
      for (let i = von; i < bis; i++) if (eigen[i]) idx.push(i);
      if (idx.length < 2) return "";
      const oben = idx.map((i) => eigen[i]), unten = idx.map((i) => best[i]).reverse();
      return `<path class="luecke ${cls}" d="${pfad([...oben, ...unten])}Z"/>`;
    };
    s += flaeche(0, nAkt, "");
    s += flaeche(nAkt - 1, punkte.length, "luecke-prog");
  }

  // Linie "heute"
  const xa = x(nAkt - 1);
  s += `<line class="jetzt" x1="${xa}" x2="${xa}" y1="${rand.o - 6}" y2="${H - rand.u}"/>`;

  // Linien
  const linie = (pts, cls) => {
    const ok = pts.filter(Boolean);
    return ok.length > 1 ? `<path class="${cls}" d="${pfad(ok)}"/>` : "";
  };
  s += linie(best.slice(0, nAkt), "linie-best");
  s += linie(best.slice(nAkt - 1), "linie-best prog");
  if (hatEigen) {
    s += linie(eigen.slice(0, nAkt), "linie-eigen");
    s += linie(eigen.slice(nAkt - 1), "linie-eigen prog");
  }

  // Werte am aktuellen Jahr
  const pa = punkte[nAkt - 1];
  const lx = xa + (punkte.length > nAkt ? 6 : -6), anker = punkte.length > nAkt ? "start" : "end";
  s += `<text class="punkt-label" x="${lx}" y="${y(pa.best) + 18}" text-anchor="${anker}" fill="var(--gletscher)">${pa.best.toFixed(0)}</text>`;
  if (pa.eigen != null)
    s += `<text class="punkt-label" x="${lx}" y="${y(pa.eigen) - 8}" text-anchor="${anker}" fill="var(--laerche)">${pa.eigen.toFixed(0)}</text>`;
  s += `<text class="achse" x="${xa}" y="${rand.o - 10}" text-anchor="middle">${pa.jahr}</text>`;

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);
  svg.classList.toggle("neu", neu);
  svg.innerHTML = s;
  document.querySelector(".leg-eigen").hidden = !hatEigen;
  document.querySelector(".leg-luecke").hidden = !hatEigen;
  document.querySelector(".leg-prog").hidden = !e.prognose.length;
}

/* ---------- Ablauf ---------- */
async function vergleichen(ev) {
  if (ev) ev.preventDefault();
  fehler("");
  const f = formularLesen();
  if (!/^\d{4}$/.test(f.plz)) return fehler("Gib eine vierstellige Postleitzahl ein.");
  const orte = PLZ[f.plz];
  if (!orte) return fehler(`Die Postleitzahl ${f.plz} ist nicht im Verzeichnis der Prämienregionen.`);
  if (!(f.alter >= 0 && f.alter <= 120)) return fehler("Gib ein Alter zwischen 0 und 120 ein.");
  const [, kt, reg, bfs] = ortWahl(orte, f.ort);
  const datei = `${kt}-${reg}`;
  try {
    regionCache[datei] ??= await json(`data/p/${datei}.json`);
  } catch {
    return fehler(`Für die Prämienregion ${kt} ${reg} sind keine Daten vorhanden.`);
  }
  const e = rechnen(regionCache[datei], f, bfs);
  if (!e) return fehler("Für diese Kombination gibt es keine Prämien. Prüfe Franchise und Modell.");
  urlSchreiben(f);
  letztesErgebnis = e;
  anzeigen(e, f);
  $("resultat").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}
const ortWahl = (orte, i) => orte[i] || orte[0];

async function start() {
  try {
    [META, PLZ] = await Promise.all([json("data/meta.json"), json("data/plz.json")]);
  } catch {
    return fehler("Die Prämiendaten konnten nicht geladen werden. Lade die Seite neu.");
  }
  $("demo-hinweis").hidden = !META.demo;
  $("stand").textContent = `Prämienjahre ${META.jahre[0]} bis ${META.jahre.at(-1)}, Daten aufbereitet am ${new Date(META.stand).toLocaleDateString("de-CH")}.`;
  kassenSetzen();
  franchisenSetzen();
  $("alter").addEventListener("input", franchisenSetzen);
  $("plz").addEventListener("input", orteSetzen);
  $("formular").addEventListener("submit", vergleichen);
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => letztesErgebnis && zeichnen(letztesErgebnis, false), 150); });
  if (urlLesen()) vergleichen();
}
start();
