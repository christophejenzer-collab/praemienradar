#!/usr/bin/env python3
"""
kk_vergleich.py – günstigste Grundversicherung nach PLZ, für eine Person oder eine Familie (bis 5),
mit Vergleich zur heutigen Kasse über alle Jahre und einer Schätzung für die nächsten Jahre.

Rechnet gleich wie die Webseite (docs/app.js) und nutzt dieselben Daten (docs/data,
erzeugt mit scripts/build_data.py). Nur Python 3.9+, keine Pakete.

Personen:  --person "ALTER,FRANCHISE,UNFALL,KASSE,MODELL"   (bis 5×, Felder ab FRANCHISE optional)
           UNFALL: ja|nein   MODELL: standard|hausarzt|hmo|telmed|andere
Beispiele:
  python kk_vergleich.py                                        # PLZ 3600, eine Person, 40 Jahre
  python kk_vergleich.py 3653 --alter 45 --franchise 2500 --unfall nein --kasse CSS
  python kk_vergleich.py 3653 --person "45,2500,nein,CSS" --person "43,2500,nein,CSS" \\
         --person "12,0,ja,CSS" --person "9,0,ja,CSS" --person "6,0,ja,CSS"
"""
import argparse
import csv
import json
import sys
from pathlib import Path

DATEN = Path(__file__).resolve().parent / "docs" / "data"
MODELLE = {"standard": "B", "hausarzt": "P", "hmo": "P", "telmed": "T", "andere": "T"}
MODELL_NAME = {"B": "Standard", "P": "Hausarzt/HMO", "T": "Telmed/andere"}
FR_ERW = [300, 500, 1000, 1500, 2000, 2500]
FR_KIN = [0, 100, 200, 300, 400, 500, 600]
MAX_PERSONEN = 5
STANDARD_PLZ = "3600"


# ---------------------------------------------------------------- Daten
def lade(name):
    p = DATEN / name
    if not p.exists():
        sys.exit(f"{p} fehlt – zuerst scripts/build_data.py ausführen.")
    return json.loads(p.read_text(encoding="utf-8"))


def akl(alter):
    return "K" if alter <= 18 else "J" if alter <= 25 else "E"


def kasse_finden(eingabe, meta):
    if not eingabe or eingabe == "-":
        return None
    e = eingabe.strip().lstrip("0")
    if e in meta["kassen"]:
        return e
    aktiv = meta.get("aktiv", list(meta["kassen"]))
    exakt = [nr for nr in aktiv if meta["kassen"][nr].lower() == eingabe.lower()]
    treffer = exakt or [nr for nr in aktiv if eingabe.lower() in meta["kassen"][nr].lower()]
    if len(treffer) == 1:
        return treffer[0]
    if treffer:
        sys.exit(f"Kasse '{eingabe}' ist mehrdeutig: " + ", ".join(meta["kassen"][t] for t in treffer))
    sys.exit(f"Kasse '{eingabe}' nicht gefunden.")


def person_lesen(text, meta, nr):
    teile = [t.strip() for t in text.split(",")]
    try:
        alter = int(teile[0])
    except ValueError:
        sys.exit(f"Person {nr}: Alter fehlt oder ist keine Zahl ('{text}').")
    k = akl(alter) == "K"
    fr = int(teile[1]) if len(teile) > 1 and teile[1] else (0 if k else 300)
    if fr not in (FR_KIN if k else FR_ERW):
        sys.exit(f"Person {nr}: Franchise {fr} ungültig. Erlaubt: {FR_KIN if k else FR_ERW}")
    u = teile[2].lower() if len(teile) > 2 and teile[2] else "ja"
    if u not in ("ja", "nein"):
        sys.exit(f"Person {nr}: Unfall muss 'ja' oder 'nein' sein.")
    modell = teile[4].lower() if len(teile) > 4 and teile[4] else "standard"
    if modell not in MODELLE:
        sys.exit(f"Person {nr}: Modell '{modell}' unbekannt. Erlaubt: {', '.join(MODELLE)}")
    return {"alter": alter, "fr": fr, "u": 1 if u == "ja" else 0,
            "kasse": kasse_finden(teile[3] if len(teile) > 3 else None, meta), "modell": MODELLE[modell]}


# ---------------------------------------------------------------- Rechnen (wie docs/app.js)
def kinder_rabatt(jd, nr, kinder, ok):
    """Geschwisterrabatt: K3 ab dem 3. Kind, K4 ab 2 Kindern für alle, K5 ab 3 Kindern für alle."""
    n = len(kinder)
    if n < 2:
        return [k["preis"] for k in kinder]

    def preis_in(gruppe, k):
        z = [r[2] for r in jd.get(f"{gruppe}|{k['p']['u']}|{k['p']['fr']}", [])
             if r[0] == nr and r[1] == k["typ"] and ok(r)]
        return min(z) if z else None

    def oder(x, y):
        return y if x is None else x

    varianten = [[k["preis"] for k in kinder], [oder(preis_in("K4", k), k["preis"]) for k in kinder]]
    if n >= 3:
        varianten.append([oder(preis_in("K5", k), k["preis"]) for k in kinder])
        ordnung = sorted(range(n), key=lambda i: -kinder[i]["p"]["alter"])  # ältestes zuerst
        v = [k["preis"] for k in kinder]
        for i in ordnung[2:]:
            v[i] = oder(preis_in("K3", kinder[i]), v[i])
        varianten.append(v)
    return min(varianten, key=sum)


def mit_rabatt(jd, personen, wahl, ok):
    preise = [w["preis"] if w else None for w in wahl]
    nach_kasse = {}
    for i, p in enumerate(personen):
        if wahl[i] and akl(p["alter"]) == "K":
            nach_kasse.setdefault(wahl[i]["nr"], []).append(i)
    for nr, idx in nach_kasse.items():
        neu = kinder_rabatt(jd, nr, [{"p": personen[i], "typ": wahl[i]["typ"], "preis": wahl[i]["preis"]} for i in idx], ok)
        for i, preis in zip(idx, neu):
            preise[i] = preis
    return preise


def jahr_rechnen(jd, personen, vergleich, ok):
    listen = [[r for r in jd.get(f"{akl(p['alter'])}|{p['u']}|{p['fr']}", []) if ok(r)] for p in personen]
    darf = lambda p, r: vergleich == "alle" or r[1] == p["modell"]  # noqa: E731

    def billigste(rows):
        return min(rows, key=lambda r: r[2]) if rows else None

    def w(r, nr=None):
        return {"nr": nr or r[0], "typ": r[1], "preis": r[2]} if r else None

    heute_wahl = [w(billigste([r for r in listen[i] if r[0] == p["kasse"] and r[1] == p["modell"]])) if p["kasse"] else None
                  for i, p in enumerate(personen)]
    heute_fehlt = any(p["kasse"] and not heute_wahl[i] for i, p in enumerate(personen))
    heute = mit_rabatt(jd, personen, heute_wahl, ok) if all(p["kasse"] for p in personen) and not heute_fehlt else None

    einzel_wahl = [w(billigste([r for r in listen[i] if darf(p, r)])) for i, p in enumerate(personen)]
    if not all(einzel_wahl):
        return None
    einzeln = mit_rabatt(jd, personen, einzel_wahl, ok)

    kassen = {r[0] for liste in listen for r in liste}
    familie = []
    for nr in kassen:
        wahl = [w(billigste([r for r in listen[i] if r[0] == nr and darf(p, r)])) for i, p in enumerate(personen)]
        if all(wahl):
            preise = mit_rabatt(jd, personen, wahl, ok)
            familie.append({"nr": nr, "wahl": wahl, "preise": preise, "total": sum(preise)})
    familie.sort(key=lambda x: x["total"])

    # Kinder gemeinsam bei einer Kasse prüfen (Geschwisterrabatt), Erwachsene bleiben bei ihrer günstigsten
    kinder = [i for i, p in enumerate(personen) if akl(p["alter"]) == "K"]
    if len(kinder) >= 2:
        kosten = lambda pr: sum(pr[i] for i in kinder)  # noqa: E731
        best_p, best_w = einzeln, einzel_wahl
        for nr in kassen:
            wahl = list(einzel_wahl)
            for i in kinder:
                wahl[i] = w(billigste([r for r in listen[i] if r[0] == nr and darf(personen[i], r)]), nr)
            if not all(wahl):
                continue
            preise = mit_rabatt(jd, personen, wahl, ok)
            if kosten(preise) < kosten(best_p) - 0.001:
                best_p, best_w = preise, wahl
        einzeln, einzel_wahl = best_p, best_w

    return {"heute": heute, "heute_wahl": heute_wahl, "heute_fehlt": heute_fehlt,
            "heute_total": sum(heute) if heute else None,
            "einzel_wahl": einzel_wahl, "einzeln": einzeln, "einzeln_total": sum(einzeln),
            "familie": familie, "eine": familie[0] if familie else None}


def rechnen(datei, personen, vergleich, bfs):
    gebiete = datei["e"]
    ok = lambda r: len(r) < 4 or bfs in gebiete[r[3]]  # noqa: E731
    verlauf = []
    for j in sorted(datei["d"], key=int):
        r = jahr_rechnen(datei["d"][j], personen, vergleich, ok)
        if r:
            verlauf.append({"jahr": int(j), **r})
    return verlauf


def prognose(verlauf, jahre):
    voll = [v for v in verlauf if v["heute_total"] is not None and v["eine"]]
    if len(voll) < 3 or jahre <= 0:
        return []
    a, z = voll[0], voll[-1]
    n = z["jahr"] - a["jahr"]
    wachs = lambda x, y: (y / x) ** (1 / n) - 1  # noqa: E731
    wh, we = wachs(a["heute_total"], z["heute_total"]), wachs(a["einzeln_total"], z["einzeln_total"])
    return [{"jahr": z["jahr"] + k, "heute": z["heute_total"] * (1 + wh) ** k,
             "einzeln": z["einzeln_total"] * (1 + we) ** k, "wh": wh, "we": we} for k in range(1, jahre + 1)]


# ---------------------------------------------------------------- Ausgabe
def chf(x):
    return f"{x:,.0f}".replace(",", "'")


def fz(x):
    return "–" if x is None else f"{x:.2f}"


def main():
    ap = argparse.ArgumentParser(description="Günstigste Grundversicherung nach PLZ (BAG-Daten)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("plz", nargs="?", default=STANDARD_PLZ, help=f"Postleitzahl (Standard {STANDARD_PLZ})")
    ap.add_argument("--gemeinde", help="falls die PLZ mehrere Gemeinden umfasst")
    ap.add_argument("--person", action="append", default=[], metavar="ALTER,FRANCHISE,UNFALL,KASSE,MODELL",
                    help=f"Person (bis {MAX_PERSONEN}×)")
    ap.add_argument("--alter", type=int, default=40, help="nur ohne --person")
    ap.add_argument("--franchise", type=int, help="nur ohne --person")
    ap.add_argument("--unfall", choices=["ja", "nein"], default="ja", help="nur ohne --person")
    ap.add_argument("--kasse", help="nur ohne --person: heutige Kasse (Name oder BAG-Nr.)")
    ap.add_argument("--kasse-modell", choices=sorted(MODELLE), default="standard", help="nur ohne --person")
    ap.add_argument("--vergleich", choices=["gleich", "alle"], default="gleich",
                    help="mit dem gleichen Modell wie heute oder mit allen Modellen vergleichen")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--prognose", type=int, default=3)
    ap.add_argument("--export", help="Verlauf als CSV speichern")
    a = ap.parse_args()

    meta, plz = lade("meta.json"), lade("plz.json")
    if len(a.person) > MAX_PERSONEN:
        sys.exit(f"Höchstens {MAX_PERSONEN} Personen.")
    if a.person:
        personen = [person_lesen(t, meta, i + 1) for i, t in enumerate(a.person)]
    else:
        fr = "" if a.franchise is None else str(a.franchise)
        personen = [person_lesen(f"{a.alter},{fr},{a.unfall},{a.kasse or '-'},{a.kasse_modell}", meta, 1)]
    fam = len(personen) > 1
    name = lambda nr: meta["kassen"].get(nr, f"BAG-Nr. {nr}")  # noqa: E731

    orte = plz.get(a.plz.strip())
    if not orte:
        sys.exit(f"PLZ {a.plz} nicht im Verzeichnis der Prämienregionen.")
    if a.gemeinde:
        orte = [o for o in orte if a.gemeinde.lower() in o[0].lower()] or sys.exit("Gemeinde passt nicht zur PLZ.")
    gemeinde, kt, reg, bfs = orte[0]
    hinweis = (" – weitere Gemeinden mit dieser PLZ: " + ", ".join(o[0] for o in orte[1:]) + " (--gemeinde)") if len(orte) > 1 else ""

    verlauf = rechnen(lade(f"p/{kt}-{reg}.json"), personen, a.vergleich, bfs)
    if not verlauf:
        sys.exit("Keine Prämien für diese Angaben.")
    akt = verlauf[-1]
    alle_kassen = all(p["kasse"] for p in personen)

    print(f"\n{a.plz} {gemeinde} ({kt}, Prämienregion {reg}){hinweis}")
    print(f"Vergleich: {'gleiches Modell wie heute' if a.vergleich == 'gleich' else 'alle Modelle'} | Prämienjahr {akt['jahr']}")
    for i, p in enumerate(personen):
        print(f"  Person {i + 1}: {p['alter']} J., Franchise {p['fr']}, Unfall {'ja' if p['u'] else 'nein'}, "
              f"heute {name(p['kasse']) if p['kasse'] else '–'} ({MODELL_NAME[p['modell']]})")

    if akt["heute_fehlt"]:
        i = next(k for k, p in enumerate(personen) if p["kasse"] and not akt["heute_wahl"][k])
        print(f"\nHinweis: {name(personen[i]['kasse'])} bietet für Person {i + 1} das Modell "
              f"{MODELL_NAME[personen[i]['modell']]} mit diesen Angaben {akt['jahr']} nicht an.")

    # Pro Person / Varianten
    if fam:
        print(f"\nPro Person {akt['jahr']} (CHF pro Monat)")
        print(f"{'':<11}{'Heute':>22}{'Einzeln':>28}{'Eine Kasse':>28}")
        for i, p in enumerate(personen):
            h = akt["heute"][i] if akt["heute"] else (akt["heute_wahl"][i]["preis"] if akt["heute_wahl"][i] else None)
            e, ew = akt["einzeln"][i], akt["einzel_wahl"][i]
            heute_txt = (name(p["kasse"])[:12] + " " + fz(h)) if h is not None else "–"
            einzeln_txt = name(ew["nr"])[:18] + " " + fz(e)
            eine_txt = (name(akt["eine"]["nr"])[:18] + " " + fz(akt["eine"]["preise"][i])) if akt["eine"] else "–"
            print(f"{'Person ' + str(i + 1):<11}{heute_txt:>22}{einzeln_txt:>28}{eine_txt:>28}")
        eine_total = akt["eine"]["total"] if akt["eine"] else None
        print(f"{'Total':<11}{fz(akt['heute_total']):>22}{fz(akt['einzeln_total']):>28}{fz(eine_total):>28}")
        print("\nPro Jahr:")
        if akt["heute_total"] is not None:
            print(f"  Heute                          CHF {chf(akt['heute_total'] * 12)}")
        print(f"  Einzeln, je günstigste Kasse   CHF {chf(akt['einzeln_total'] * 12)}")
        if akt["eine"]:
            print(f"  Eine Kasse ({name(akt['eine']['nr'])})".ljust(33) + f"CHF {chf(akt['eine']['total'] * 12)}")
            print(f"  Mehrkosten für nur eine Kasse  CHF {chf(max(0, (akt['eine']['total'] - akt['einzeln_total']) * 12))}")

    # Rangliste
    gemeinsam = personen[0]["kasse"] if all(p["kasse"] == personen[0]["kasse"] for p in personen) else None
    titel = f"Eine Kasse für alle {len(personen)} Personen" if fam else "Günstigste Kassen"
    print(f"\n{titel} {akt['jahr']} (CHF pro Monat)")
    for i, x in enumerate(akt["familie"]):
        if i < a.top or x["nr"] == gemeinsam:
            modelle = ", ".join(sorted({MODELL_NAME[w["typ"]] for w in x["wahl"]}))
            mark = "  ← heute" if x["nr"] == gemeinsam else ""
            print(f"{i + 1:>3}. {name(x['nr']):<26}{modelle:<28}{x['total']:>9.2f}{mark}")

    # Verlauf
    spalte_eine = f"{'Eine Kasse':>12}" if fam else ""
    print(f"\n{'Jahr':<6}{'Günstigste' if not fam else 'Einzeln':>10}{spalte_eine}{'Heute':>10}{'Diff/Jahr':>11}   günstigste Kasse(n)")
    for v in verlauf:
        kassen_txt = ", ".join(dict.fromkeys(name(w["nr"]) for w in v["einzel_wahl"]))
        ht = v["heute_total"]
        eine_t = v["eine"]["total"] if v["eine"] else None
        diff = chf((ht - v["einzeln_total"]) * 12) if ht is not None else "–"
        eine_txt = f"{fz(eine_t):>12}" if fam else ""
        print(f"{v['jahr']:<6}{v['einzeln_total']:>10.2f}{eine_txt}{fz(ht):>10}{diff:>11}   {kassen_txt}")

    if alle_kassen and not akt["heute_fehlt"]:
        vor = [v for v in verlauf[:-1] if v["heute_total"] is not None]
        if vor:
            print(f"\nMögliche Ersparnis {vor[0]['jahr']}–{vor[-1]['jahr']}: CHF "
                  + chf(sum(max(0, v["heute_total"] - v["einzeln_total"]) * 12 for v in vor)))
        print(f"Ersparnis {akt['jahr']} bei Wechsel (einzeln): CHF {chf(max(0, (akt['heute_total'] - akt['einzeln_total']) * 12))}")
        p = prognose(verlauf, a.prognose)
        if p:
            print(f"Schätzung {p[0]['jahr']}–{p[-1]['jahr']} (Ø-Wachstum günstigste {p[0]['we']:+.1%}, heute {p[0]['wh']:+.1%}): "
                  f"CHF {chf(sum(max(0, x['heute'] - x['einzeln']) * 12 for x in p))}")

    if a.export:
        with open(a.export, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Jahr", "Einzeln CHF/Mt.", "Eine Kasse", "Eine Kasse CHF/Mt.", "Heute CHF/Mt."])
            for v in verlauf:
                w.writerow([v["jahr"], round(v["einzeln_total"], 2), name(v["eine"]["nr"]) if v["eine"] else "",
                            round(v["eine"]["total"], 2) if v["eine"] else "",
                            round(v["heute_total"], 2) if v["heute_total"] is not None else ""])
        print(f"\nExport: {a.export}")


if __name__ == "__main__":
    main()
