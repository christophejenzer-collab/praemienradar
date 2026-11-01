#!/usr/bin/env python3
"""
kk_vergleich.py – günstigste Grundversicherung nach PLZ, mit Vergleich zur eigenen Kasse
über alle verfügbaren Jahre und einer Schätzung für die nächsten Jahre.

Nutzt dieselben aufbereiteten BAG-Daten wie die Webseite (docs/data, erzeugt mit
scripts/build_data.py). Keine weiteren Abhängigkeiten ausser Python 3.9+.

Beispiele:
  python kk_vergleich.py 3653
  python kk_vergleich.py 3653 --alter 45 --franchise 2500 --unfall nein --kasse CSS
  python kk_vergleich.py 3653 --kasse Helsana --kasse-modell hausarzt --vergleich alle --export verlauf.csv
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


def lade(name):
    p = DATEN / name
    if not p.exists():
        sys.exit(f"{p} fehlt – zuerst scripts/build_data.py ausführen.")
    return json.loads(p.read_text(encoding="utf-8"))


def kasse_finden(eingabe, meta):
    e = eingabe.strip().lstrip("0")
    if e in meta["kassen"]:
        return e
    treffer = [nr for nr in meta.get("aktiv", meta["kassen"]) if eingabe.lower() in meta["kassen"][nr].lower()]
    if len(treffer) == 1:
        return treffer[0]
    if treffer:
        sys.exit(f"'{eingabe}' ist mehrdeutig: " + ", ".join(meta["kassen"][t] for t in treffer))
    sys.exit(f"Kasse '{eingabe}' nicht gefunden.")


def rechnen(datei, akl, unfall, fr, kasse, kasse_typ, vergleich_typ, bfs):
    gebiete = datei["e"]
    ok = lambda r: len(r) < 4 or bfs in gebiete[r[3]]  # noqa: E731
    key = f"{akl}|{unfall}|{fr}"
    verlauf = []
    for jahr in sorted(datei["d"], key=int):
        liste = [r for r in datei["d"][jahr].get(key, []) if ok(r)]
        pool = [r for r in liste if not vergleich_typ or r[1] == vergleich_typ]
        if not pool:
            continue
        best = min(pool, key=lambda r: r[2])
        eigen = min((r[2] for r in liste if r[0] == kasse and r[1] == kasse_typ), default=None)
        verlauf.append({"jahr": int(jahr), "best": best, "eigen": eigen})
    if not verlauf:
        return verlauf, []
    letzte = [r for r in datei["d"][str(verlauf[-1]["jahr"])].get(key, []) if ok(r)]
    pool = sorted((r for r in letzte if not vergleich_typ or r[1] == vergleich_typ), key=lambda r: r[2])
    rang, gesehen = [], set()
    for r in pool:
        if r[0] not in gesehen:
            gesehen.add(r[0])
            rang.append(r)
    return verlauf, rang


def prognose(verlauf, jahre):
    v = [x for x in verlauf if x["eigen"] is not None]
    if len(v) < 3 or jahre <= 0:
        return None
    a, z = v[0], v[-1]
    n = z["jahr"] - a["jahr"]
    wb = (z["best"][2] / a["best"][2]) ** (1 / n) - 1
    we = (z["eigen"] / a["eigen"]) ** (1 / n) - 1
    zeilen = [{"jahr": z["jahr"] + k, "best": z["best"][2] * (1 + wb) ** k,
               "eigen": z["eigen"] * (1 + we) ** k} for k in range(1, jahre + 1)]
    return zeilen, wb, we


def chf(x):
    return f"{x:,.0f}".replace(",", "'")


def main():
    ap = argparse.ArgumentParser(description="Günstigste Grundversicherung nach PLZ (BAG-Daten)")
    ap.add_argument("plz")
    ap.add_argument("--gemeinde", help="falls die PLZ mehrere Gemeinden umfasst")
    ap.add_argument("--alter", type=int, default=40)
    ap.add_argument("--franchise", type=int)
    ap.add_argument("--unfall", choices=["ja", "nein"], default="ja")
    ap.add_argument("--kasse", help="aktuelle Kasse (Name oder BAG-Nr.)")
    ap.add_argument("--kasse-modell", choices=sorted(MODELLE), default="standard")
    ap.add_argument("--vergleich", choices=["gleich", "alle"], default="gleich",
                    help="gleiches Modell wie die eigene Kasse oder alle Modelle")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--prognose", type=int, default=3)
    ap.add_argument("--export", help="Verlauf als CSV speichern")
    a = ap.parse_args()

    meta, plz = lade("meta.json"), lade("plz.json")
    akl = "K" if a.alter <= 18 else "J" if a.alter <= 25 else "E"
    fr = a.franchise if a.franchise is not None else (0 if akl == "K" else 300)
    if fr not in (FR_KIN if akl == "K" else FR_ERW):
        sys.exit(f"Franchise {fr} ungültig. Erlaubt: {FR_KIN if akl == 'K' else FR_ERW}")

    orte = plz.get(a.plz.strip())
    if not orte:
        sys.exit(f"PLZ {a.plz} nicht im Verzeichnis der Prämienregionen.")
    if a.gemeinde:
        orte = [o for o in orte if a.gemeinde.lower() in o[0].lower()] or sys.exit("Gemeinde passt nicht zur PLZ.")
    if len(orte) > 1:
        print("Die PLZ umfasst mehrere Gemeinden: " + ", ".join(o[0] for o in orte)
              + " – Auswahl mit --gemeinde. Gezeigt wird: " + orte[0][0])
    gemeinde, kt, reg, bfs = orte[0]

    kasse = kasse_finden(a.kasse, meta) if a.kasse else None
    ktyp = MODELLE[a.kasse_modell]
    vtyp = ktyp if a.vergleich == "gleich" else None
    datei = lade(f"p/{kt}-{reg}.json")
    verlauf, rang = rechnen(datei, akl, 1 if a.unfall == "ja" else 0, fr, kasse, ktyp, vtyp, bfs)
    if not verlauf:
        sys.exit("Keine Prämien für diese Angaben.")
    name = lambda nr: meta["kassen"].get(nr, f"BAG-Nr. {nr}")  # noqa: E731
    akt = verlauf[-1]

    print(f"\n{gemeinde} ({kt}, Region {reg}) | Alter {a.alter} | Franchise {fr} | Unfall {a.unfall}"
          f" | Vergleich: {MODELL_NAME[vtyp] if vtyp else 'alle Modelle'}"
          + (f" | Eigene: {name(kasse)}, {MODELL_NAME[ktyp]}" if kasse else ""))

    print(f"\nGünstigste Kassen {akt['jahr']} (CHF pro Monat)")
    for i, r in enumerate(rang[: a.top], 1):
        mark = "  ← deine Kasse" if r[0] == kasse else ""
        print(f"{i:>3}. {name(r[0]):<28}{MODELL_NAME[r[1]]:<15}{r[2]:>9.2f}{mark}")

    print(f"\n{'Jahr':<6}{'Günstigste':<28}{'CHF/Mt.':>9}" + (f"{'Eigene':>10}{'Diff/Jahr':>11}" if kasse else ""))
    for v in verlauf:
        z = f"{v['jahr']:<6}{name(v['best'][0])[:27]:<28}{v['best'][2]:>9.2f}"
        if kasse:
            z += (f"{v['eigen']:>10.2f}{chf((v['eigen'] - v['best'][2]) * 12):>11}"
                  if v["eigen"] is not None else f"{'–':>10}{'–':>11}")
        print(z)

    if kasse:
        vg = [v for v in verlauf[:-1] if v["eigen"] is not None]
        if vg:
            print(f"\nMögliche Ersparnis {vg[0]['jahr']}–{vg[-1]['jahr']}: CHF "
                  + chf(sum(max(0, v['eigen'] - v['best'][2]) * 12 for v in vg)))
        if akt["eigen"] is not None:
            print(f"Ersparnis {akt['jahr']} bei Wechsel: CHF {chf(max(0, akt['eigen'] - akt['best'][2]) * 12)}")
        p = prognose(verlauf, a.prognose)
        if p:
            zeilen, wb, we = p
            print(f"Schätzung {zeilen[0]['jahr']}–{zeilen[-1]['jahr']} (Ø-Wachstum günstigste {wb:+.1%}, "
                  f"eigene {we:+.1%}): CHF {chf(sum(max(0, z['eigen'] - z['best']) * 12 for z in zeilen))}")

    if a.export:
        with open(a.export, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Jahr", "Günstigste Kasse", "Modell", "Prämie günstigste", "Prämie eigene"])
            for v in verlauf:
                w.writerow([v["jahr"], name(v["best"][0]), MODELL_NAME[v["best"][1]], v["best"][2],
                            v["eigen"] if v["eigen"] is not None else ""])
        print(f"\nExport: {a.export}")


if __name__ == "__main__":
    main()
