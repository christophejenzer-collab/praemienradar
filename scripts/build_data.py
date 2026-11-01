#!/usr/bin/env python3
"""
build_data.py – bereitet die BAG-Prämiendaten für die Webseite auf.

Eingabe:  data-src/praemien/   Prämien_CH.csv + Archiv_Praemien_JJJJ.zip (opendata.swiss)
          data-src/Praemienregionen.xlsx|csv   (BAG: Gemeinden/PLZ -> Prämienregion)
          data-src/Versicherer.csv  (optional: Versicherer;Name)
Ausgabe:  docs/data/meta.json, docs/data/plz.json, docs/data/p/<KT>-<R>.json

  python scripts/build_data.py            # echte Daten
  python scripts/build_data.py --demo     # synthetische Demo-Daten
"""
import argparse
import json
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402
from kk_vergleich import finde_spalte, lies_praemien, lies_tabelle, region_code  # noqa: E402

OUT = ROOT / "docs" / "data"
TYP = {"TAR-BASE": "B", "TAR-HAM": "H", "TAR-HMO": "M", "TAR-DIV": "D"}
AKL = {"AKL-ERW": "E", "AKL-JUG": "J", "AKL-KIN": "K"}
MIN_JAHR = 2018  # ältere Jahre weglassen (Dateigrösse)


def schreibe(pfad: Path, obj):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def plz_tabelle(reg: pd.DataFrame) -> dict:
    c_plz = finde_spalte(reg, "PLZ", "NPA", "Postleitzahl")
    c_kt = finde_spalte(reg, "Kanton", "Canton", "KT")
    c_reg = finde_spalte(reg, "Region", "Prämienregion")
    c_ort = next((c for c in reg.columns
                  if c.lower() in ("ort", "gemeinde", "ortschaft", "localité", "commune")), None)
    out = {}
    for _, r in reg.iterrows():
        plz = str(r[c_plz]).strip().split(".")[0]
        if not plz.isdigit():
            continue
        eintrag = [str(r[c_ort]).strip() if c_ort else "", str(r[c_kt]).strip(),
                   int(region_code(r[c_reg])[-1])]
        out.setdefault(plz, [])
        if eintrag not in out[plz]:
            out[plz].append(eintrag)
    return out


def baue(praemien: pd.DataFrame, plz: dict, namen: dict, demo: bool):
    p = praemien[praemien["Jahr"] >= MIN_JAHR].copy()
    p = p[p["Tariftyp"].isin(TYP) & p["Altersklasse"].isin(AKL)]
    if "Altersuntergruppe" in p.columns:  # Kinder: nur 1. Kind (K1)
        p = p[(p["Altersklasse"] != "AKL-KIN") | p["Altersuntergruppe"].fillna("").isin(["K1", ""])]
    p["fr"] = p["Franchise"].str.extract(r"(\d+)")[0].astype(int)
    p["u"] = (p["Unfalleinschluss"] == "MIT-UNF").astype(int)
    p["r"] = p["Region"].map(region_code).str[-1]

    # pro Kasse + Modell nur das günstigste Produkt
    p = (p.sort_values("Prämie")
          .drop_duplicates(["Jahr", "Kanton", "r", "Altersklasse", "u", "fr", "Versicherer", "Tariftyp"]))

    for f in (OUT / "p").glob("*.json"):
        f.unlink()
    for (kt, r), g in p.groupby(["Kanton", "r"]):
        daten = {}
        for (jahr, akl, u, fr), h in g.groupby(["Jahr", "Altersklasse", "u", "fr"]):
            schl = f"{AKL[akl]}|{u}|{fr}"
            daten.setdefault(str(int(jahr)), {})[schl] = [
                [v, TYP[t], round(float(pr), 2)]
                for v, t, pr in zip(h["Versicherer"], h["Tariftyp"], h["Prämie"])]
        schreibe(OUT / "p" / f"{kt}-{r}.json", daten)

    jahre = sorted(int(j) for j in p["Jahr"].unique())
    kassen = {v: namen.get(v, f"BAG-Nr. {v}") for v in sorted(p["Versicherer"].unique(), key=int)}
    schreibe(OUT / "plz.json", plz)
    schreibe(OUT / "meta.json", {"demo": demo, "stand": date.today().isoformat(),
                                 "jahre": jahre, "kassen": kassen})
    print(f"OK: {len(jahre)} Jahre ({jahre[0]}–{jahre[-1]}), {len(kassen)} Kassen, "
          f"{len(plz)} PLZ, {p.groupby(['Kanton', 'r']).ngroups} Regionen")


def demo_daten():
    random.seed(7)
    orte = {"3653": [["Oberhofen am Thunersee", "BE", 2], ["Hilterfingen", "BE", 2]],
            "3600": [["Thun", "BE", 2]], "3011": [["Bern", "BE", 1]],
            "3800": [["Interlaken", "BE", 3]], "8001": [["Zürich", "ZH", 1]],
            "6300": [["Zug", "ZG", 0]], "1003": [["Lausanne", "VD", 1]]}
    stufe = {("BE", 1): 1.0, ("BE", 2): .92, ("BE", 3): .85, ("ZH", 1): 1.02,
             ("ZG", 0): .72, ("VD", 1): 1.08}
    kassen = {str(i): f"Demo-Kasse {chr(64 + i)}" for i in range(1, 9)}
    k_basis = {k: random.uniform(.9, 1.12) for k in kassen}
    k_wachs = {k: random.uniform(.025, .075) for k in kassen}
    rows = []
    for jahr in range(2019, 2028):
        for (kt, r), f_reg in stufe.items():
            for k in kassen:
                for akl, f_akl, frs in (("AKL-ERW", 1, [300, 500, 1000, 1500, 2000, 2500]),
                                        ("AKL-JUG", .78, [300, 500, 1000, 1500, 2000, 2500]),
                                        ("AKL-KIN", .26, [0, 100, 200, 300, 400, 500, 600])):
                    for typ, f_typ in (("TAR-BASE", 1), ("TAR-HAM", .88),
                                       ("TAR-HMO", .84), ("TAR-DIV", .86)):
                        for fr in frs:
                            for unf, f_unf in (("MIT-UNF", 1), ("OHN-UNF", .93)):
                                basis = 400 * f_reg * f_akl * k_basis[k] * f_typ * f_unf
                                rabatt = (fr - frs[0]) * (.7 if akl != "AKL-KIN" else .6) / 12
                                pr = (basis - rabatt) * (1 + k_wachs[k]) ** (jahr - 2019)
                                rows.append((k, kt, f"PR-REG CH{r}", akl, unf, typ, f"FRA-{fr}",
                                             round(max(pr, 40), 2), jahr))
    df = pd.DataFrame(rows, columns=["Versicherer", "Kanton", "Region", "Altersklasse",
                                     "Unfalleinschluss", "Tariftyp", "Franchise", "Prämie", "Jahr"])
    return df, orte, kassen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        df, plz, namen = demo_daten()
        baue(df, plz, namen, demo=True)
        return
    src = ROOT / "data-src"
    reg_datei = next((p for p in src.glob("Praemienregionen.*")), None)
    if not reg_datei:
        sys.exit("data-src/Praemienregionen.xlsx fehlt (BAG-Verzeichnis der Prämienregionen).")
    namen = {}
    if (src / "Versicherer.csv").exists():
        n = lies_tabelle(src / "Versicherer.csv")
        namen = dict(zip(n.iloc[:, 0].str.strip().str.lstrip("0"), n.iloc[:, 1].str.strip()))
    baue(lies_praemien(src / "praemien"), plz_tabelle(lies_tabelle(reg_datei)), namen, demo=False)


if __name__ == "__main__":
    main()
