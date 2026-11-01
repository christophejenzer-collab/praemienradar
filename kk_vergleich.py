#!/usr/bin/env python3
"""
kk_vergleich.py – günstigste Grundversicherung (OKP) nach PLZ finden,
mit Vergleich zur eigenen Kasse über mehrere Jahre und Prognose.

Datenquellen (BAG, jährlich Ende September aktualisiert):
  1. Prämien:  opendata.swiss -> "Krankenversicherungsprämien"
               -> Prämien_CH.csv (aktuelles Jahr) + Archiv_Praemien_JJJJ.zip (Vorjahre)
               Alles in EINEN Ordner legen (Standard: ./daten). ZIPs werden direkt gelesen.
  2. Prämienregionen: BAG-Verzeichnis nach PLZ/Gemeinde (xlsx/csv)
  3. optional: Versicherer.csv mit Spalten  Versicherer;Name

Beispiele:
  python kk_vergleich.py 3653
  python kk_vergleich.py 3653 --alter 45 --franchise 2500 --unfall nein --kasse CSS
  python kk_vergleich.py 3653 --kasse 8 --kasse-modell hausarzt --prognose 3 --export verlauf.csv
"""
import argparse
import io
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

MODELLE = {
    "standard": "TAR-BASE", "base": "TAR-BASE",
    "hausarzt": "TAR-HAM", "ham": "TAR-HAM",
    "hmo": "TAR-HMO",
    "andere": "TAR-DIV", "telmed": "TAR-DIV", "div": "TAR-DIV",
}
FRANCHISEN_ERW = [300, 500, 1000, 1500, 2000, 2500]
FRANCHISEN_KIN = [0, 100, 200, 300, 400, 500, 600]


# ---------------------------------------------------------------- Einlesen
def _csv(quelle) -> pd.DataFrame:
    roh = quelle.read() if hasattr(quelle, "read") else Path(quelle).read_bytes()
    for enc in ("utf-8-sig", "latin-1"):
        try:
            text = roh.decode(enc)
            return pd.read_csv(io.StringIO(text), sep=None, engine="python", dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError("Encoding nicht erkannt")


def lies_tabelle(pfad: Path) -> pd.DataFrame:
    if not pfad.exists():
        sys.exit(f"Datei fehlt: {pfad}")
    if pfad.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(pfad, dtype=str)
    return _csv(pfad)


def _jahr_aus_name(name: str):
    m = re.search(r"(20\d\d)", name)
    return m.group(1) if m else None


def lies_praemien(ordner: Path) -> pd.DataFrame:
    """Liest alle Prämien-CSVs im Ordner, auch innerhalb von Archiv-ZIPs."""
    teile = []
    quellen = sorted(ordner.glob("*"))
    for p in quellen:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.lower().endswith(".csv") and "pr" in n.lower() and "_eu" not in n.lower():
                        with z.open(n) as f:
                            teile.append((_csv(f), _jahr_aus_name(p.name) or _jahr_aus_name(n)))
        elif p.suffix.lower() == ".csv" and "pr" in p.name.lower() and "_eu" not in p.name.lower():
            teile.append((_csv(p), _jahr_aus_name(p.name)))
    if not teile:
        sys.exit(f"Keine Prämiendateien in {ordner} gefunden.")

    dfs = []
    for df, jahr_datei in teile:
        df.columns = [c.strip() for c in df.columns]
        if "Jahr" not in df.columns:
            if not jahr_datei:
                continue
            df["Jahr"] = jahr_datei
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df["Jahr"] = pd.to_numeric(df["Jahr"].str.extract(r"(\d{4})")[0], errors="coerce")
    df["Prämie"] = pd.to_numeric(df["Prämie"].str.replace(",", "."), errors="coerce")
    df["Versicherer"] = df["Versicherer"].str.strip().str.lstrip("0")
    # gleiche Datei doppelt im Ordner -> nur einmal zählen
    return df.dropna(subset=["Jahr", "Prämie"]).drop_duplicates()


def finde_spalte(df, *kandidaten):
    norm = {c.lower().strip(): c for c in df.columns}
    for k in kandidaten:
        if k.lower() in norm:
            return norm[k.lower()]
    for k in kandidaten:
        for low, orig in norm.items():
            if k.lower() in low:
                return orig
    sys.exit(f"Spalte {kandidaten} nicht gefunden. Vorhanden: {list(df.columns)}")


def region_code(wert) -> str:
    ziffer = "".join(ch for ch in str(wert) if ch.isdigit())[-1:] or "0"
    return f"PR-REG CH{ziffer}"


def altersklasse(alter: int) -> str:
    return "AKL-KIN" if alter <= 18 else "AKL-JUG" if alter <= 25 else "AKL-ERW"


def regionen_fuer_plz(regionen, plz):
    c_plz = finde_spalte(regionen, "PLZ", "NPA", "Postleitzahl")
    c_kt = finde_spalte(regionen, "Kanton", "Canton", "KT")
    c_reg = finde_spalte(regionen, "Region", "Prämienregion")
    c_ort = next((c for c in regionen.columns
                  if c.lower() in ("ort", "gemeinde", "ortschaft", "localité", "commune")), None)
    t = regionen[regionen[c_plz].astype(str).str.strip() == plz]
    return pd.DataFrame({
        "Kanton": t[c_kt].str.strip(),
        "Region": t[c_reg].map(region_code),
        "Ort": t[c_ort] if c_ort else "",
    }).drop_duplicates()


# ---------------------------------------------------------------- Auswertung
def filtere(p, kanton, region, akl, franchise, unfall):
    f = p[(p["Kanton"] == kanton) & (p["Region"] == region) & (p["Altersklasse"] == akl)
          & (p["Unfalleinschluss"] == unfall) & (p["Franchise"] == f"FRA-{franchise}")]
    if akl == "AKL-KIN" and "Altersuntergruppe" in f.columns:
        f = f[f["Altersuntergruppe"].isin(["K1", ""]) | f["Altersuntergruppe"].isna()]
    return f


def kasse_suchen(eingabe, namen, vorhandene):
    """BAG-Nr. oder Namensteil -> BAG-Nr."""
    e = eingabe.strip().lstrip("0")
    if e in vorhandene:
        return e
    treffer = {nr for nr, n in namen.items() if eingabe.lower() in n.lower()}
    if len(treffer) == 1:
        return treffer.pop()
    if len(treffer) > 1:
        sys.exit(f"'{eingabe}' ist mehrdeutig: " + ", ".join(f"{namen[t]} ({t})" for t in treffer))
    sys.exit(f"Kasse '{eingabe}' nicht gefunden (BAG-Nr. oder Name; Namen brauchen Versicherer.csv).")


def verlauf(f, kasse, kasse_typ, vergleich_typ, namen):
    zeilen = []
    for jahr, g in f.groupby("Jahr"):
        pool = g[g["Tariftyp"] == vergleich_typ] if vergleich_typ else g
        if pool.empty:
            continue
        best = pool.loc[pool["Prämie"].idxmin()]
        z = {"Jahr": int(jahr),
             "Günstigste": namen.get(best["Versicherer"], f"BAG-Nr. {best['Versicherer']}"),
             "Modell günstigste": best["Tariftyp"],
             "Prämie günstigste": best["Prämie"]}
        if kasse:
            eigene = g[(g["Versicherer"] == kasse) & (g["Tariftyp"] == kasse_typ)]
            z["Prämie eigene"] = eigene["Prämie"].min() if not eigene.empty else float("nan")
            z["Ersparnis/Mt."] = z["Prämie eigene"] - z["Prämie günstigste"]
            z["Ersparnis/Jahr"] = z["Ersparnis/Mt."] * 12
        zeilen.append(z)
    return pd.DataFrame(zeilen)


def prognose(v, jahre):
    """Fortschreibung mit mittlerem jährlichem Wachstum (CAGR) – nur Schätzung."""
    basis = v.dropna(subset=["Prämie eigene"]) if "Prämie eigene" in v else v
    if len(basis) < 3 or jahre <= 0 or "Prämie eigene" not in basis:
        return None
    erstes, letztes = basis.iloc[0], basis.iloc[-1]
    n = letztes["Jahr"] - erstes["Jahr"]
    zeilen = []
    w_best = (letztes["Prämie günstigste"] / erstes["Prämie günstigste"]) ** (1 / n) - 1
    w_eig = (letztes["Prämie eigene"] / erstes["Prämie eigene"]) ** (1 / n) - 1
    for k in range(1, jahre + 1):
        z = {"Jahr": int(letztes["Jahr"]) + k,
             "Prämie günstigste": letztes["Prämie günstigste"] * (1 + w_best) ** k}
        z["Prämie eigene"] = letztes["Prämie eigene"] * (1 + w_eig) ** k
        z["Ersparnis/Mt."] = z["Prämie eigene"] - z["Prämie günstigste"]
        z["Ersparnis/Jahr"] = z["Ersparnis/Mt."] * 12
        zeilen.append(z)
    return pd.DataFrame(zeilen), w_best, w_eig


def chf(x):
    return "     –" if pd.isna(x) else f"{x:>9,.2f}".replace(",", "'")


def drucke(v, prog, kasse_name, akt_jahr):
    hat_eigen = "Prämie eigene" in v
    kopf = f"{'Jahr':<6}{'Günstigste Kasse':<28}{'Modell':<10}{'CHF/Mt.':>10}"
    if hat_eigen:
        kopf += f"{'Eigene':>10}{'Diff/Mt.':>10}{'Diff/Jahr':>11}"
    print(kopf)
    print("-" * len(kopf))
    for _, d in v.iterrows():
        z = (f"{int(d['Jahr']):<6}{d['Günstigste'][:27]:<28}{d['Modell günstigste'][:9]:<10}"
             f"{chf(d['Prämie günstigste']):>10}")
        if hat_eigen:
            z += f"{chf(d['Prämie eigene']):>10}{chf(d['Ersparnis/Mt.']):>10}{chf(d['Ersparnis/Jahr']):>11}"
        print(z + ("   ← aktuell" if d["Jahr"] == akt_jahr else ""))

    if not hat_eigen:
        return
    vg = v[(v["Jahr"] < akt_jahr)].dropna(subset=["Ersparnis/Jahr"])
    if not vg.empty:
        print(f"\nVerpasste Ersparnis {int(vg['Jahr'].min())}–{akt_jahr - 1}: "
              f"CHF {vg['Ersparnis/Jahr'].sum():,.0f} ({len(vg)} Jahre)".replace(",", "'"))
    akt = v[v["Jahr"] == akt_jahr]["Ersparnis/Jahr"]
    if not akt.empty and not pd.isna(akt.iloc[0]):
        print(f"Ersparnis {akt_jahr} bei Wechsel:  CHF {akt.iloc[0]:,.0f}".replace(",", "'"))

    if prog is not None:
        df, w_best, w_eig = prog
        print(f"\nPrognose (Schätzung, Ø-Wachstum günstigste {w_best:+.1%}/J., "
              f"{kasse_name} {w_eig:+.1%}/J.):")
        for _, r in df.iterrows():
            print(f"  {int(r['Jahr'])}: günstigste {chf(r['Prämie günstigste'])}  "
                  f"eigene {chf(r['Prämie eigene'])}  "
                  f"→ Ersparnis CHF {r['Ersparnis/Jahr']:,.0f}/Jahr".replace(",", "'"))
        print(f"  Summe Prognosejahre: CHF {df['Ersparnis/Jahr'].sum():,.0f}".replace(",", "'"))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Günstigste Grundversicherung nach PLZ")
    ap.add_argument("plz")
    ap.add_argument("--alter", type=int, default=30)
    ap.add_argument("--franchise", type=int)
    ap.add_argument("--unfall", choices=["ja", "nein"], default="ja")
    ap.add_argument("--modell", choices=sorted(MODELLE), help="Vergleichsmodell (leer = alle)")
    ap.add_argument("--kasse", help="aktuelle Kasse: BAG-Nr. oder Name")
    ap.add_argument("--kasse-modell", choices=sorted(MODELLE), default="standard")
    ap.add_argument("--prognose", type=int, default=3, help="Jahre Fortschreibung (0 = aus)")
    ap.add_argument("--daten", default="daten", help="Ordner mit Prämien-CSVs/ZIPs")
    ap.add_argument("--regionen", default="Praemienregionen.xlsx")
    ap.add_argument("--namen", default="Versicherer.csv")
    ap.add_argument("--export", help="Verlauf als CSV speichern")
    a = ap.parse_args()

    akl = altersklasse(a.alter)
    franchise = a.franchise if a.franchise is not None else (0 if akl == "AKL-KIN" else 300)
    erlaubt = FRANCHISEN_KIN if akl == "AKL-KIN" else FRANCHISEN_ERW
    if franchise not in erlaubt:
        sys.exit(f"Franchise {franchise} ungültig. Erlaubt: {erlaubt}")

    praemien = lies_praemien(Path(a.daten))
    regionen = lies_tabelle(Path(a.regionen))
    namen = {}
    if Path(a.namen).exists():
        n = lies_tabelle(Path(a.namen))
        namen = dict(zip(n.iloc[:, 0].str.strip().str.lstrip("0"), n.iloc[:, 1].str.strip()))

    kasse = kasse_suchen(a.kasse, namen, set(praemien["Versicherer"])) if a.kasse else None
    kasse_name = namen.get(kasse, f"BAG-Nr. {kasse}") if kasse else None
    unfall = "MIT-UNF" if a.unfall == "ja" else "OHN-UNF"
    vergleich_typ = MODELLE.get(a.modell) if a.modell else None
    akt_jahr = int(praemien["Jahr"].max())

    orte = regionen_fuer_plz(regionen, a.plz.strip())
    if orte.empty:
        sys.exit(f"PLZ {a.plz} nicht im Regionenverzeichnis gefunden.")

    print(f"\nPLZ {a.plz} | Alter {a.alter} ({akl}) | Franchise {franchise} | Unfall {a.unfall}"
          f" | Vergleich: {a.modell or 'alle Modelle'}"
          + (f" | Eigene: {kasse_name} ({a.kasse_modell})" if kasse else ""))
    print(f"Jahre in den Daten: {int(praemien['Jahr'].min())}–{akt_jahr}")
    print("Hinweis: Regionenzuteilung von heute wird auf alle Jahre angewendet.")

    alle = []
    for _, o in orte.iterrows():
        print(f"\n== {o['Ort']} ({o['Kanton']}, {o['Region']}) ==")
        f = filtere(praemien, o["Kanton"], o["Region"], akl, franchise, unfall)
        v = verlauf(f, kasse, MODELLE[a.kasse_modell], vergleich_typ, namen)
        if v.empty:
            print("Keine Treffer – Filter prüfen.")
            continue
        prog = prognose(v, a.prognose) if kasse else None
        drucke(v, prog, kasse_name, akt_jahr)
        v.insert(0, "Ort", o["Ort"])
        alle.append(v)

    if a.export and alle:
        pd.concat(alle).round(2).to_csv(a.export, sep=";", index=False, encoding="utf-8-sig")
        print(f"\nExport: {a.export}")


if __name__ == "__main__":
    main()
