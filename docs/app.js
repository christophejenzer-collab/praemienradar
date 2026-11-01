"use strict";
/* Prämienradar – rechnet komplett im Browser mit den vorbereiteten BAG-Daten (docs/data).
   Bis 5 Personen: Vergleich "jede Person einzeln" vs. "eine Kasse für alle" inkl. Geschwisterrabatt. */

const MODELL = { B: "Standard", P: "Hausarzt/HMO", T: "Telmed/andere" };
const FR_ERW = [300, 500, 1000, 1500, 2000, 2500];
const FR_KIN = [0, 100, 200, 300, 400, 500, 600];
const MAX_PERSONEN = 5;
const PROGNOSE_JAHRE = 3;

const $ = (id) => document.getElementById(id);
const chf = (x, d = 0) => "CHF " + x.toLocaleString("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const zahl = (x, d = 2) => x.toLocaleString("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const summe = (a) => a.reduce((t, x) => t + x, 0);

let META, PLZ;
const regionCache = {};
let letztesErgebnis = null;

async function json(pfad) {
  const r = await fetch(pfad);
  if (!r.ok) throw new Error(`${pfad}: ${r.status}`);
  return r.json();
}
const kasseName = (nr) => META.kassen[nr] || `BAG-Nr. ${nr}`;

/* ================================================================ Formular */
function kassenOptionen() {
  const aktiv = META.aktiv || Object.keys(META.kassen);
  return `<option value="">keiner bestimmten Kasse</option>` +
    aktiv.map((nr) => [nr, META.kassen[nr]]).sort((a, b) => a[1].localeCompare(b[1], "de"))
      .map(([nr, n]) => `<option value="${nr}">${esc(n)}</option>`).join("");
}

function franchisenSetzen(li) {
  const kind = Number(li.querySelector(".alter").value) <= 18;
  const liste = kind ? FR_KIN : FR_ERW;
  const sel = li.querySelector(".franchise");
  const alt = Number(sel.value);
  sel.innerHTML = liste.map((f) => `<option value="${f}">${f.toLocaleString("de-CH")}er</option>`).join("");
  sel.value = liste.includes(alt) ? alt : liste[0];
}

function personenBeschriften() {
  const lis = [...$("personen").children];
  lis.forEach((li, i) => {
    li.querySelector(".wer").textContent = lis.length === 1 ? "Ich bin" : i === 0 ? "Person 1 (ich) ist" : `Person ${i + 1} ist`;
    li.querySelector(".weg").hidden = lis.length === 1;
    li.querySelector(".weg").setAttribute("aria-label", `Person ${i + 1} entfernen`);
  });
  $("plus").disabled = lis.length >= MAX_PERSONEN;
  $("plus").textContent = lis.length === 1 ? "Person hinzufügen" : `Person hinzufügen (${lis.length} von ${MAX_PERSONEN})`;
}

function personHinzu(werte) {
  const li = $("person-vorlage").content.firstElementChild.cloneNode(true);
  li.querySelector(".kasse").innerHTML = kassenOptionen();
  const erste = $("personen").firstElementChild;
  const v = werte || {
    alter: erste ? 10 : 40, fr: null, u: "1",
    kasse: erste ? erste.querySelector(".kasse").value : "",
    modell: erste ? erste.querySelector(".modell").value : "B",
  };
  li.querySelector(".alter").value = v.alter;
  franchisenSetzen(li);
  if (v.fr != null) li.querySelector(".franchise").value = v.fr;
  li.querySelector(".unfall").value = v.u;
  li.querySelector(".kasse").value = v.kasse;
  li.querySelector(".modell").value = v.modell;
  li.querySelector(".alter").addEventListener("input", () => franchisenSetzen(li));
  li.querySelector(".weg").addEventListener("click", () => { li.remove(); personenBeschriften(); });
  $("personen").append(li);
  personenBeschriften();
  return li;
}

function orteSetzen() {
  const orte = PLZ[$("plz").value.trim()] || [];
  $("ort").innerHTML = orte.map((o, i) => `<option value="${i}">${esc(o[0])}</option>`).join("");
  $("ort-wahl").hidden = orte.length < 2;
}

function formularLesen() {
  return {
    plz: $("plz").value.trim(),
    ort: Number($("ort").value || 0),
    vergleich: $("vergleich").value,
    personen: [...$("personen").children].map((li) => ({
      alter: Number(li.querySelector(".alter").value),
      fr: Number(li.querySelector(".franchise").value),
      u: li.querySelector(".unfall").value,
      kasse: li.querySelector(".kasse").value,
      modell: li.querySelector(".modell").value,
    })),
  };
}

function urlSchreiben(f) {
  const q = new URLSearchParams({ plz: f.plz, v: f.vergleich });
  if (f.ort) q.set("o", f.ort);
  q.set("p", f.personen.map((p) => [p.alter, p.fr, p.u, p.kasse || "-", p.modell].join(".")).join("_"));
  history.replaceState(null, "", "?" + q.toString());
}

function urlLesen() {
  const q = new URLSearchParams(location.search);
  if (!q.get("plz")) return false;
  $("plz").value = q.get("plz");
  orteSetzen();
  if (q.get("o")) $("ort").value = q.get("o");
  if (q.get("v")) $("vergleich").value = q.get("v");
  $("personen").innerHTML = "";
  if (q.get("p")) {
    for (const t of q.get("p").split("_").slice(0, MAX_PERSONEN)) {
      const [alter, fr, u, kasse, modell] = t.split(".");
      personHinzu({ alter, fr, u, kasse: kasse === "-" ? "" : kasse, modell: MODELL[modell] ? modell : "B" });
    }
  } else { // alte Links mit einer Person
    personHinzu({ alter: q.get("alter") || 40, fr: q.get("fr"), u: q.get("u") || "1", kasse: q.get("k") || "", modell: MODELL[q.get("m")] ? q.get("m") : "B" });
  }
  return true;
}

/* Standort -> PLZ über den Geodienst des Bundes (swisstopo, Amtliches Ortschaftenverzeichnis) */
function plzAusAntwort(daten) {
  for (const r of (daten && daten.results) || []) {
    const a = r.attributes || r.properties || {};
    for (const k of ["plz", "plz4", "postleitzahl", "zip"]) {
      const m = String(a[k] ?? "").match(/\b(\d{4})\b/);
      if (m) return m[1];
    }
    const m = String(r.label || a.label || "").match(/\b(\d{4})\b/);
    if (m) return m[1];
  }
  return null;
}

function standortVerwenden() {
  const info = $("standort-info"), knopf = $("standort");
  if (!("geolocation" in navigator)) { info.textContent = "Dein Browser kann den Standort nicht ermitteln."; return; }
  knopf.disabled = true;
  info.textContent = "Standort wird ermittelt …";
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { longitude: lon, latitude: lat } = pos.coords;
    const url = "https://api3.geo.admin.ch/rest/services/api/MapServer/identify?geometryType=esriGeometryPoint" +
      `&geometry=${lon},${lat}&sr=4326&layers=all:ch.swisstopo-vd.ortschaftenverzeichnis_plz` +
      "&tolerance=0&returnGeometry=false&imageDisplay=100,100,96" +
      `&mapExtent=${lon - 0.01},${lat - 0.01},${lon + 0.01},${lat + 0.01}&lang=de`;
    try {
      const r = await fetch(url);
      const plz = plzAusAntwort(await r.json());
      if (!plz) throw new Error("keine PLZ");
      if (!PLZ[plz]) { info.textContent = `Dein Standort hat die PLZ ${plz}, die nicht im Verzeichnis der Prämienregionen steht.`; return; }
      $("plz").value = plz;
      orteSetzen();
      info.textContent = `PLZ ${plz} übernommen.`;
    } catch {
      info.textContent = "Die PLZ konnte nicht bestimmt werden. Gib sie bitte von Hand ein.";
    } finally {
      knopf.disabled = false;
    }
  }, (err) => {
    knopf.disabled = false;
    info.textContent = err.code === 1 ? "Standortzugriff abgelehnt. Gib die PLZ von Hand ein." : "Der Standort ist gerade nicht verfügbar.";
  }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 });
}

function fehler(text) {
  $("fehler").textContent = text;
  $("fehler").hidden = !text;
}

/* ================================================================ Rechnen */
function akl(alter) { return alter <= 18 ? "K" : alter <= 25 ? "J" : "E"; }

/* Kinder bei derselben Kasse: Rabatt-Tarife K3 (ab 3. Kind), K4 (ab 2 Kindern für alle), K5 (ab 3 Kindern für alle).
   kinder: [{p, typ, preis}] – liefert neue Preise in gleicher Reihenfolge. */
function kinderRabatt(jahrDaten, nr, kinder, erhaeltlich) {
  const n = kinder.length;
  if (n < 2) return kinder.map((k) => k.preis);
  const preisIn = (gruppe, k) => {
    const z = (jahrDaten[`${gruppe}|${k.p.u}|${k.p.fr}`] || [])
      .filter((r) => r[0] === nr && r[1] === k.typ && erhaeltlich(r));
    return z.length ? Math.min(...z.map((r) => r[2])) : null;
  };
  const varianten = [kinder.map((k) => k.preis)];
  varianten.push(kinder.map((k) => preisIn("K4", k) ?? k.preis));
  if (n >= 3) {
    varianten.push(kinder.map((k) => preisIn("K5", k) ?? k.preis));
    // ab dem 3. Kind (nach Alter, ältestes zuerst)
    const ordnung = kinder.map((k, i) => i).sort((a, b) => kinder[b].p.alter - kinder[a].p.alter);
    const v = kinder.map((k) => k.preis);
    ordnung.slice(2).forEach((i) => { v[i] = preisIn("K3", kinder[i]) ?? v[i]; });
    varianten.push(v);
  }
  return varianten.reduce((a, b) => (summe(b) < summe(a) ? b : a));
}

/* Preise je Person für eine Zuordnung Person -> {nr, typ, preis}, mit Geschwisterrabatt je Kasse */
function mitRabatt(jahrDaten, personen, wahl, erhaeltlich) {
  const preise = wahl.map((w) => (w ? w.preis : null));
  const nachKasse = {};
  personen.forEach((p, i) => {
    if (wahl[i] && akl(p.alter) === "K") (nachKasse[wahl[i].nr] ??= []).push(i);
  });
  for (const [nr, idx] of Object.entries(nachKasse)) {
    const neu = kinderRabatt(jahrDaten, nr, idx.map((i) => ({ p: personen[i], typ: wahl[i].typ, preis: wahl[i].preis })), erhaeltlich);
    idx.forEach((i, k) => { preise[i] = neu[k]; });
  }
  return preise;
}

function jahrRechnen(jahrDaten, personen, vergleich, erhaeltlich) {
  const listen = personen.map((p) => (jahrDaten[`${akl(p.alter)}|${p.u}|${p.fr}`] || []).filter(erhaeltlich));
  const darf = (p, r) => vergleich === "alle" || r[1] === p.modell;
  const billigste = (rows) => rows.reduce((a, b) => (!a || b[2] < a[2] ? b : a), null);

  // Heute
  const heuteWahl = personen.map((p, i) => {
    if (!p.kasse) return null;
    const r = billigste(listen[i].filter((r) => r[0] === p.kasse && r[1] === p.modell));
    return r ? { nr: r[0], typ: r[1], preis: r[2] } : null;
  });
  const heuteFehlt = personen.some((p, i) => p.kasse && !heuteWahl[i]);
  const heute = personen.every((p) => p.kasse) && !heuteFehlt ? mitRabatt(jahrDaten, personen, heuteWahl, erhaeltlich) : null;

  // Einzeln: jede Person bei der für sie günstigsten Kasse
  const einzelWahl = personen.map((p, i) => {
    const r = billigste(listen[i].filter((r) => darf(p, r)));
    return r ? { nr: r[0], typ: r[1], preis: r[2] } : null;
  });
  if (einzelWahl.some((w) => !w)) return null;
  const einzeln = mitRabatt(jahrDaten, personen, einzelWahl, erhaeltlich);

  // Eine Kasse für alle
  const kassen = new Set(listen.flat().map((r) => r[0]));
  const familie = [];
  for (const nr of kassen) {
    const wahl = personen.map((p, i) => {
      const r = billigste(listen[i].filter((r) => r[0] === nr && darf(p, r)));
      return r ? { nr, typ: r[1], preis: r[2] } : null;
    });
    if (wahl.some((w) => !w)) continue;
    const preise = mitRabatt(jahrDaten, personen, wahl, erhaeltlich);
    familie.push({ nr, wahl, preise, total: summe(preise) });
  }
  familie.sort((a, b) => a.total - b.total);

  // Kinder: Geschwisterrabatt gibt es nur bei derselben Kasse. Prüfen, ob alle Kinder zusammen
  // bei einer Kasse günstiger sind als je einzeln – Erwachsene bleiben bei ihrer günstigsten Kasse.
  let einzelnPreise = einzeln, einzelnWahl = einzelWahl;
  const kinder = personen.map((p, i) => i).filter((i) => akl(personen[i].alter) === "K");
  if (kinder.length >= 2) {
    const kostenKinder = (preise) => summe(kinder.map((i) => preise[i]));
    let bestPreise = einzeln, bestWahl = einzelWahl;
    for (const nr of kassen) {
      const wahl = einzelWahl.slice();
      let ok = true;
      for (const i of kinder) {
        const r = billigste(listen[i].filter((r) => r[0] === nr && darf(personen[i], r)));
        if (!r) { ok = false; break; }
        wahl[i] = { nr, typ: r[1], preis: r[2] };
      }
      if (!ok) continue;
      const preise = mitRabatt(jahrDaten, personen, wahl, erhaeltlich);
      if (kostenKinder(preise) < kostenKinder(bestPreise) - 0.001) { bestPreise = preise; bestWahl = wahl; }
    }
    einzelnPreise = bestPreise;
    einzelnWahl = bestWahl;
  }

  return {
    heute, heuteWahl, heuteFehlt,
    einzelWahl: einzelnWahl, einzeln: einzelnPreise, einzelnTotal: summe(einzelnPreise),
    familie, eine: familie[0] || null,
    heuteTotal: heute ? summe(heute) : null,
  };
}

function rechnen(datei, f, bfs) {
  const gebiete = datei.e || [];
  const erhaeltlich = (r) => r.length < 4 || gebiete[r[3]].includes(bfs);
  const jahre = Object.keys(datei.d).map(Number).sort((a, b) => a - b);
  const verlauf = [];
  for (const j of jahre) {
    const r = jahrRechnen(datei.d[j], f.personen, f.vergleich, erhaeltlich);
    if (r) verlauf.push({ jahr: j, ...r });
  }
  if (!verlauf.length) return null;

  // Schätzung: mittleres jährliches Wachstum über die Jahre mit vollständigen Werten
  const prognose = [];
  const voll = verlauf.filter((v) => v.heuteTotal != null && v.eine);
  if (voll.length >= 3) {
    const a = voll[0], z = voll[voll.length - 1], n = z.jahr - a.jahr;
    const w = (x, y) => Math.pow(y / x, 1 / n) - 1;
    const wH = w(a.heuteTotal, z.heuteTotal), wE = w(a.einzelnTotal, z.einzelnTotal), wF = w(a.eine.total, z.eine.total);
    for (let k = 1; k <= PROGNOSE_JAHRE; k++) {
      prognose.push({
        jahr: z.jahr + k,
        heute: z.heuteTotal * (1 + wH) ** k,
        einzeln: z.einzelnTotal * (1 + wE) ** k,
        eine: z.eine.total * (1 + wF) ** k,
      });
    }
  }
  return { verlauf, aktuell: verlauf[verlauf.length - 1], prognose, f };
}

/* ================================================================ Darstellen */
function personLabel(p, i) {
  const art = p.alter <= 18 ? "Kind" : p.alter <= 25 ? "junge Erw." : "Erw.";
  return `Person ${i + 1}<span class="kasse">${p.alter} J., ${art}</span>`;
}

function anzeigen(e) {
  const f = e.f, n = f.personen.length, akt = e.aktuell, fam = n > 1;
  const alleKassen = f.personen.every((p) => p.kasse);
  const zahlEl = $("fazit-zahl"), text = $("fazit-text");
  zahlEl.classList.remove("gut");

  const sparEinzeln = akt.heuteTotal != null ? (akt.heuteTotal - akt.einzelnTotal) * 12 : null;
  const sparEine = akt.heuteTotal != null && akt.eine ? (akt.heuteTotal - akt.eine.total) * 12 : null;
  const adminPreis = akt.eine ? (akt.eine.total - akt.einzelnTotal) * 12 : null;

  if (akt.heuteFehlt) {
    const i = akt.heuteWahl.findIndex((w, k) => f.personen[k].kasse && !w);
    const p = f.personen[i];
    zahlEl.textContent = chf(akt.einzelnTotal, 2);
    text.textContent = `${kasseName(p.kasse)} bietet ${fam ? `für Person ${i + 1} ` : ""}das Modell ${MODELL[p.modell]} mit diesen Angaben ${akt.jahr} nicht an. ` +
      `Günstigste Lösung: ${chf(akt.einzelnTotal, 2)} pro Monat.`;
  } else if (alleKassen && sparEinzeln > 0.5) {
    zahlEl.textContent = chf(sparEinzeln);
    if (!fam) {
      const w = akt.einzelWahl[0];
      text.textContent = `So viel sparst du ${akt.jahr} pro Jahr, wenn du von ${kasseName(f.personen[0].kasse)} zu ${kasseName(w.nr)} (${MODELL[w.typ]}) wechselst.`;
    } else if (akt.eine && adminPreis < 0.5) {
      text.textContent = `So viel spart ihr ${akt.jahr} pro Jahr, wenn alle zu ${kasseName(akt.eine.nr)} wechseln. Einzeln auf mehrere Kassen verteilt wird es nicht günstiger.`;
    } else {
      text.textContent = `So viel spart ihr ${akt.jahr} pro Jahr, wenn jede Person zur für sie günstigsten Kasse wechselt.` +
        (akt.eine ? ` Mit einer Kasse für alle (${kasseName(akt.eine.nr)}) sind es ${chf(Math.max(0, sparEine))}, also ${chf(adminPreis)} weniger, dafür nur eine Kasse.` : "");
    }
  } else if (alleKassen) {
    zahlEl.textContent = "Bestwert";
    zahlEl.classList.add("gut");
    text.textContent = fam ? `Ihr seid ${akt.jahr} mit diesen Angaben bereits bei den günstigsten Kassen.`
      : `${kasseName(f.personen[0].kasse)} ist ${akt.jahr} mit diesen Angaben bereits die günstigste Kasse.`;
  } else if (!fam) {
    const w = akt.einzelWahl[0];
    zahlEl.textContent = chf(w.preis, 2);
    text.textContent = `So viel kostet die günstigste Grundversicherung ${akt.jahr} pro Monat: ${kasseName(w.nr)}, Modell ${MODELL[w.typ]}.`;
  } else {
    zahlEl.textContent = chf(akt.einzelnTotal, 2);
    text.textContent = `So viel kostet die Grundversicherung für ${n} Personen ${akt.jahr} pro Monat, wenn jede Person die günstigste Kasse wählt.` +
      (akt.eine ? ` Mit einer Kasse für alle (${kasseName(akt.eine.nr)}): ${chf(akt.eine.total, 2)}.` : "");
  }

  // Kennzahlen
  const s = [];
  if (fam) {
    if (akt.heuteTotal != null) s.push([`Heute ${akt.jahr}`, chf(akt.heuteTotal * 12) + " / Jahr"]);
    s.push(["Einzeln, je günstigste Kasse", chf(akt.einzelnTotal * 12) + " / Jahr"]);
    if (akt.eine) s.push([`Eine Kasse: ${kasseName(akt.eine.nr)}`, chf(akt.eine.total * 12) + " / Jahr"]);
    if (adminPreis != null) s.push(["Mehrkosten für nur eine Kasse", chf(Math.max(0, adminPreis)) + " / Jahr"]);
  }
  if (alleKassen && !akt.heuteFehlt) {
    const vor = e.verlauf.filter((v) => v.jahr < akt.jahr && v.heuteTotal != null);
    if (vor.length) s.push([`Mögliche Ersparnis ${vor[0].jahr}–${akt.jahr - 1}`, chf(summe(vor.map((v) => Math.max(0, v.heuteTotal - v.einzelnTotal) * 12)))]);
    if (!fam) s.push([`Ersparnis ${akt.jahr}`, chf(Math.max(0, sparEinzeln))]);
    if (e.prognose.length) s.push([`Schätzung ${e.prognose[0].jahr}–${e.prognose.at(-1).jahr}`, chf(summe(e.prognose.map((p) => Math.max(0, p.heute - p.einzeln) * 12)))]);
  } else if (!fam) {
    const pool = rangliste(e).liste;
    const teuer = pool.at(-1);
    s.push([`Günstigste ${akt.jahr}`, chf(pool[0].preis, 2) + " / Mt."]);
    s.push([`Teuerste ${akt.jahr}`, chf(teuer.preis, 2) + " / Mt."]);
    s.push(["Spanne pro Jahr", chf((teuer.preis - pool[0].preis) * 12)]);
  }
  $("summen").innerHTML = s.map(([t, w]) => `<div><dt>${esc(t)}</dt><dd>${esc(w)}</dd></div>`).join("");

  // Pro Person (nur Familie)
  $("familie").hidden = !fam;
  if (fam) {
    const zelle = (preis, nr, typ, best) => preis == null ? `<td class="zahl">–</td>` :
      `<td class="zahl${best ? " best" : ""}">${zahl(preis)}<span class="kasse">${esc(kasseName(nr))}${typ && f.vergleich === "alle" ? ", " + MODELL[typ] : ""}</span></td>`;
    $("pro-person").innerHTML = f.personen.map((p, i) => `<tr>
      <td>${personLabel(p, i)}</td>
      ${p.kasse ? zelle(akt.heute ? akt.heute[i] : akt.heuteWahl[i] && akt.heuteWahl[i].preis, p.kasse, null) : "<td class='zahl'>–</td>"}
      ${zelle(akt.einzeln[i], akt.einzelWahl[i].nr, akt.einzelWahl[i].typ, true)}
      ${akt.eine ? zelle(akt.eine.preise[i], akt.eine.nr, akt.eine.wahl[i].typ) : "<td class='zahl'>–</td>"}
    </tr>`).join("");
    $("pro-person-summe").innerHTML = `<tr><td>Total</td>
      <td class="zahl">${akt.heuteTotal != null ? zahl(akt.heuteTotal) : "–"}</td>
      <td class="zahl">${zahl(akt.einzelnTotal)}</td>
      <td class="zahl">${akt.eine ? zahl(akt.eine.total) : "–"}</td></tr>`;
  }

  // Rangliste
  const { titel, liste, modellSpalte } = rangliste(e);
  const gemeinsam = f.personen.every((p) => p.kasse && p.kasse === f.personen[0].kasse) ? f.personen[0].kasse : null;
  const pos = liste.findIndex((r) => r.nr === gemeinsam);
  const zeilen = liste.slice(0, 10).map((r, i) => [i + 1, r]);
  if (pos >= 10) zeilen.push([pos + 1, liste[pos]]);
  $("rang-titel").textContent = titel;
  $("rang-modell-kopf").textContent = modellSpalte;
  $("rang").innerHTML = zeilen.map(([p, r]) => `
    <tr class="${r.nr === gemeinsam ? "eigen" : ""}">
      <td>${p}</td><td>${esc(kasseName(r.nr))}${r.nr === gemeinsam ? (fam ? " (eure Kasse)" : " (deine Kasse)") : ""}</td>
      <td>${esc(r.modell)}</td><td class="zahl">${zahl(r.preis)}</td>
      <td class="zahl jahr-spalte">${zahl(r.preis * 12, 0)}</td>
    </tr>`).join("");

  // Jahrestabelle
  $("jahre").innerHTML = [...e.verlauf].reverse().map((v) => {
    const best = v.einzelnTotal;
    const name = fam ? (v.eine ? `Einzeln; eine Kasse: ${kasseName(v.eine.nr)} ${zahl(v.eine.total)}` : "Einzeln")
      : `${kasseName(v.einzelWahl[0].nr)} (${MODELL[v.einzelWahl[0].typ]})`;
    return `<tr><td>${v.jahr}</td><td>${esc(name)}</td><td class="zahl">${zahl(best)}</td>
      <td class="zahl">${v.heuteTotal != null ? zahl(v.heuteTotal) : "–"}</td>
      <td class="zahl">${v.heuteTotal != null ? zahl((v.heuteTotal - best) * 12, 0) : "–"}</td></tr>`;
  }).join("");

  $("resultat").hidden = false;
  zeichnen(e, true);
}

function rangliste(e) {
  const akt = e.aktuell, f = e.f;
  if (f.personen.length > 1) {
    return {
      titel: `Eine Kasse für alle ${f.personen.length} Personen, ${akt.jahr}`,
      modellSpalte: "Modelle",
      liste: akt.familie.map((x) => ({
        nr: x.nr, preis: x.total,
        modell: [...new Set(x.wahl.map((w) => MODELL[w.typ]))].join(", "),
      })),
    };
  }
  return {
    titel: `Die günstigsten Kassen ${akt.jahr}` + (f.vergleich === "gleich" ? ` im Modell ${MODELL[f.personen[0].modell]}` : ""),
    modellSpalte: "Modell",
    liste: akt.familie.map((x) => ({ nr: x.nr, preis: x.total, modell: MODELL[x.wahl[0].typ] })),
  };
}

function zeichnen(e, neu) {
  const svg = $("chart");
  const W = Math.max(300, svg.parentElement.clientWidth);
  const H = W < 520 ? 250 : 340;
  const rand = { l: W < 520 ? 40 : 56, r: W < 520 ? 22 : 28, o: 22, u: 30 };
  const fam = e.f.personen.length > 1;

  const punkte = [
    ...e.verlauf.map((v) => ({ jahr: v.jahr, best: v.einzelnTotal, eigen: v.heuteTotal, eine: v.eine ? v.eine.total : null })),
    ...e.prognose.map((p) => ({ jahr: p.jahr, best: p.einzeln, eigen: p.heute, eine: p.eine })),
  ];
  const werte = punkte.flatMap((p) => [p.best, p.eigen, fam ? p.eine : null]).filter((x) => x != null);
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
  const eine = punkte.map((p, i) => (p.eine != null ? [x(i), y(p.eine)] : null));

  let s = `<defs><pattern id="schraffur" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
    <rect width="6" height="6" fill="var(--enzian-hell)"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--enzian)" stroke-width="1.2" opacity=".5"/></pattern></defs>`;

  for (let k = 0; k <= 4; k++) {
    const v = lo + ((hi - lo) * k) / 4, yy = y(v);
    s += `<line class="raster" x1="${rand.l}" x2="${W - rand.r}" y1="${yy}" y2="${yy}"/>`;
    s += `<text class="achse" x="${rand.l - 8}" y="${yy + 4}" text-anchor="end">${Math.round(v)}</text>`;
  }
  const jede = W < 520 && punkte.length > 7 ? 2 : 1;
  punkte.forEach((p, i) => {
    if ((punkte.length - 1 - i) % jede === 0) s += `<text class="achse" x="${x(i)}" y="${H - 8}" text-anchor="middle">${p.jahr}</text>`;
  });

  s += `<path class="berg" d="${pfad(best)}L${best.at(-1)[0]},${H - rand.u}L${best[0][0]},${H - rand.u}Z"/>`;

  if (hatEigen) {
    const flaeche = (von, bis, cls) => {
      const idx = [];
      for (let i = von; i < bis; i++) if (eigen[i]) idx.push(i);
      if (idx.length < 2) return "";
      return `<path class="luecke ${cls}" d="${pfad([...idx.map((i) => eigen[i]), ...idx.map((i) => best[i]).reverse()])}Z"/>`;
    };
    s += flaeche(0, nAkt, "") + flaeche(nAkt - 1, punkte.length, "luecke-prog");
  }

  const xa = x(nAkt - 1);
  s += `<line class="jetzt" x1="${xa}" x2="${xa}" y1="${rand.o - 6}" y2="${H - rand.u}"/>`;

  const linie = (pts, cls) => {
    const ok = pts.filter(Boolean);
    return ok.length > 1 ? `<path class="${cls}" d="${pfad(ok)}"/>` : "";
  };
  if (fam) s += linie(eine.slice(0, nAkt), "linie-eine") + linie(eine.slice(nAkt - 1), "linie-eine prog");
  s += linie(best.slice(0, nAkt), "linie-best") + linie(best.slice(nAkt - 1), "linie-best prog");
  if (hatEigen) s += linie(eigen.slice(0, nAkt), "linie-eigen") + linie(eigen.slice(nAkt - 1), "linie-eigen prog");

  const pa = punkte[nAkt - 1];
  const lx = xa + (punkte.length > nAkt ? 6 : -6), anker = punkte.length > nAkt ? "start" : "end";
  s += `<text class="punkt-label" x="${lx}" y="${y(pa.best) + 18}" text-anchor="${anker}" fill="var(--gletscher)">${pa.best.toFixed(0)}</text>`;
  if (pa.eigen != null) s += `<text class="punkt-label" x="${lx}" y="${y(pa.eigen) - 8}" text-anchor="${anker}" fill="var(--laerche)">${pa.eigen.toFixed(0)}</text>`;
  s += `<text class="achse" x="${xa}" y="${rand.o - 10}" text-anchor="middle">${pa.jahr}</text>`;

  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);
  svg.classList.toggle("neu", neu);
  svg.innerHTML = s;
  document.querySelector(".leg-eigen").hidden = !hatEigen;
  document.querySelector(".leg-luecke").hidden = !hatEigen;
  document.querySelector(".leg-prog").hidden = !e.prognose.length;
  document.querySelector(".leg-eine").hidden = !fam;
  document.querySelector(".leg-best").textContent = fam ? "Einzeln, je günstigste Kasse" : "Günstigste Kasse";
}

/* ================================================================ Ablauf */
async function vergleichen(ev) {
  if (ev) ev.preventDefault();
  fehler("");
  const f = formularLesen();
  if (!/^\d{4}$/.test(f.plz)) return fehler("Gib eine vierstellige Postleitzahl ein.");
  const orte = PLZ[f.plz];
  if (!orte) return fehler(`Die Postleitzahl ${f.plz} ist nicht im Verzeichnis der Prämienregionen.`);
  const falsch = f.personen.findIndex((p) => !(p.alter >= 0 && p.alter <= 120));
  if (falsch >= 0) return fehler(`Gib für Person ${falsch + 1} ein Alter zwischen 0 und 120 ein.`);
  const [, kt, reg, bfs] = orte[f.ort] || orte[0];
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
  anzeigen(e);
  $("resultat").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

async function start() {
  try {
    [META, PLZ] = await Promise.all([json("data/meta.json"), json("data/plz.json")]);
  } catch {
    return fehler("Die Prämiendaten konnten nicht geladen werden. Lade die Seite neu.");
  }
  $("demo-hinweis").hidden = !META.demo;
  $("stand").textContent = `Prämienjahre ${META.jahre[0]} bis ${META.jahre.at(-1)}, Daten aufbereitet am ${new Date(META.stand).toLocaleDateString("de-CH")}.`;
  $("plz").addEventListener("input", () => { orteSetzen(); $("standort-info").textContent = ""; });
  $("standort").addEventListener("click", standortVerwenden);
  $("plus").addEventListener("click", () => {
    const li = personHinzu();
    li.querySelector(".alter").focus();
    li.querySelector(".alter").select();
  });
  $("formular").addEventListener("submit", vergleichen);
  let t;
  addEventListener("resize", () => { clearTimeout(t); t = setTimeout(() => letztesErgebnis && zeichnen(letztesErgebnis, false), 150); });
  if (urlLesen()) vergleichen();
  else { orteSetzen(); personHinzu(); }
}
start();
