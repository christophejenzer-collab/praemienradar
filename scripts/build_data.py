#!/usr/bin/env python3
"""
build_data.py – bereitet die BAG-Prämiendaten für Webseite und CLI auf.

Eingabe (Ordner data-src/roh, Inhalt des Branches "rohdaten"):
  praemien_aktuell.csv(.zip), praemien_JJJJ.csv(.zip)     BAG Prämien CH (altes und neues Format)
  einzugsgebiete_aktuell.csv(.zip), einzugsgebiete_JJJJ…   eingeschränkte Tätigkeitsgebiete
  praemienregionen-JJJJ.xlsx                               BAG/priminfo: Gemeinde/PLZ -> Region
  versicherer.xlsx                                         BAG: zugelassene Krankenversicherer
Ausgabe:
  docs/data/meta.json, docs/data/plz.json, docs/data/p/<KT>-<R>.json

  python scripts/build_data.py [--roh data-src/roh]
"""
import argparse
import io
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data"

# Modelle über alle Jahre vereinheitlichen (BAG hat die Codes 2027 geändert)
MODELL = {
    "BASE": "B", "TAR-BASE": "B",
    "PRAXIS": "P", "TAR-HAM": "P", "TAR-HMO": "P",
    "TEL_DIG": "T", "FLEX": "T", "PHARM": "T", "TAR-DIV": "T",
}
# Kinder: K1 = ohne Rabatt, K3 = Rabatt ab 3. Kind, K4 = ab 2 Kindern für alle, K5 = ab 3 Kindern für alle
UNTERGRUPPE = {"K1", "K3", "K4", "K5", "J1", "E1"}

# Inzwischen fusionierte/aufgelöste Kassen (Quelle: BAG-Verzeichnis 1.1.2021, Mutationslisten 2024–2026)
FRUEHERE = {
    "57": "Moove Sympany", "62": "SUPRA-1846", "182": "PROVITA", "558": "KVF",
    "762": "Kolping", "774": "Easy Sana", "829": "KLuG", "901": "sanavals",
    "994": "Progrès", "1142": "Institut Ingenbohl", "1331": "Stoffel", "1362": "Simplon",
    "1529": "INTRAS", "1569": "Arcosana", "1570": "vivacare", "1575": "Compact",
    "1577": "Sanagate",
}  # Kinder: K1 = Standardtarif Kind


# ---------------------------------------------------------------- Einlesen
def lies_csv(pfad: Path) -> pd.DataFrame:
    if pfad.suffix == ".zip":
        with zipfile.ZipFile(pfad) as z:
            roh = z.read(z.namelist()[0])
    else:
        roh = pfad.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = roh.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if text.split("\n", 1)[0].count(";") > text.split("\n", 1)[0].count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str)


def dateien(roh: Path, praefix: str):
    """praemien_aktuell / praemien_2026 … -> {Name: Pfad}, egal ob .csv oder .csv.zip"""
    out = {}
    for p in sorted(roh.glob(f"{praefix}_*")):
        schl = p.name.split(".")[0]
        if schl not in out or p.suffix == ".csv":
            out[schl] = p
    return out


def normalisiere(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    jahr = "Geschäftsjahr" if "Geschäftsjahr" in df else "Jahr"
    d = pd.DataFrame({
        "jahr": pd.to_numeric(df[jahr], errors="coerce"),
        "nr": df["Versicherer"].str.strip().str.lstrip("0"),
        "kt": df["Kanton"].str.strip(),
        "reg": df["Region"].str.extract(r"(\d)\s*$")[0],
        "akl": df["Altersklasse"].str.extract(r"(KIN|JUG|ERW)")[0].map({"KIN": "K", "JUG": "J", "ERW": "E"}),
        "u": df["Unfalleinschluss"].str.upper().str.startswith("MIT").astype(int),
        "tarif": df["Tarif"].str.strip(),
        "typ": df["Tariftyp"].str.strip().map(MODELL),
        "ug": df.get("Altersuntergruppe", pd.Series("", index=df.index)).fillna(""),
        "fr": pd.to_numeric(df["Franchise"].str.extract(r"(\d+)\s*$")[0], errors="coerce"),
        "pr": pd.to_numeric(df["Prämie"].str.replace(",", "."), errors="coerce"),
    })
    d = d[d["ug"].isin(UNTERGRUPPE) | (d["ug"] == "")]
    kind_rabatt = (d["akl"] == "K") & d["ug"].isin(["K3", "K4", "K5"])
    d.loc[kind_rabatt, "akl"] = d.loc[kind_rabatt, "ug"]
    return d.dropna(subset=["jahr", "reg", "akl", "typ", "fr", "pr"]).astype({"jahr": int, "fr": int})


def lies_einzug(pfad: Path) -> dict:
    """(nr, kt, reg, tarif) -> frozenset BFS-Nummern, nur für eingeschränkte Tarife."""
    df = lies_csv(pfad)
    df.columns = [c.strip() for c in df.columns]
    c_bfs = next(c for c in df.columns if "BFS" in c)
    df = df[df["Eingeschränkt"].str.upper().eq("Y")]
    out = {}
    for _, r in df.iterrows():
        bfs = frozenset(int(x) for x in re.findall(r"\d+", str(r[c_bfs])))
        reg = re.search(r"(\d)\s*$", r["Region"]).group(1)
        out[(r["Versicherer"].strip().lstrip("0"), r["Kanton"].strip(), reg, r["Tarif"].strip())] = bfs
    return out


def lies_regionen(pfad: Path) -> dict:
    """PLZ -> [[Gemeinde, Kanton, Region, BFS], …] aus Blatt A_COM."""
    roh = pd.read_excel(pfad, sheet_name="A_COM", header=None, dtype=str)
    kopf = roh.index[roh.iloc[:, 0].astype(str).str.contains("BFS", na=False)][0]
    df = roh.iloc[kopf + 1:].copy()
    df.columns = ["bfs", "kt", "gemeinde", "reg", "bezirk", "plz", "ort"][: df.shape[1]]
    df = df.dropna(subset=["bfs", "plz"])
    out = {}
    for _, r in df.iterrows():
        plz = str(r["plz"]).strip().split(".")[0]
        reg = re.search(r"(\d)\s*$", str(r["reg"]).strip())
        if not (plz.isdigit() and reg):
            continue
        e = [str(r["gemeinde"]).strip(), str(r["kt"]).strip(), int(reg.group(1)), int(float(r["bfs"]))]
        out.setdefault(plz, [])
        if e not in out[plz]:
            out[plz].append(e)
    for v in out.values():
        v.sort(key=lambda e: e[0])
    return out


def lies_versicherer(pfad: Path) -> dict:
    roh = pd.read_excel(pfad, sheet_name=None, header=None, dtype=str)
    blatt = next(v for k, v in roh.items() if k.strip().lower() == "index")
    namen = {}
    for _, r in blatt.iterrows():
        werte = [str(x).strip() for x in r if str(x).strip() not in ("", "nan")]
        if len(werte) >= 2 and werte[0].isdigit() and werte[1] != "x":
            n = re.sub(r"\s+", " ", werte[1].replace("’", "'")).strip()
            n = re.sub(r"(-Basis)?( (Gesundheits|Kranken)versicherung)?( AG| SA)$", "", n)
            namen[werte[0]] = n
    return namen


# ---------------------------------------------------------------- Aufbereiten
def baue(roh: Path):
    praemien = dateien(roh, "praemien")
    if not praemien:
        sys.exit(f"Keine Prämiendateien in {roh}")
    teile = []
    for name, p in praemien.items():
        d = normalisiere(lies_csv(p))
        print(f"  {name}: {len(d):>7} Zeilen, Jahre {sorted(d['jahr'].unique())}")
        teile.append(d)
    df = pd.concat(teile).drop_duplicates()
    # gleiche Jahre aus aktuell + Archiv nur einmal (Archiv hat Vorrang bei Doppel – identisch)
    df = df.drop_duplicates(["jahr", "nr", "kt", "reg", "akl", "u", "tarif", "typ", "fr"])
    print("  Kinder-Rabattgruppen:", df[df["akl"].str.startswith("K")].groupby("akl").size().to_dict())

    einzug = {}
    for name, p in dateien(roh, "einzugsgebiete").items():
        jahr = re.search(r"(\d{4})", name)
        jahr = int(jahr.group(1)) if jahr else int(df["jahr"].max())
        einzug[jahr] = lies_einzug(p)
        print(f"  {name}: {len(einzug[jahr])} eingeschränkte Tarife ({jahr})")

    reg_datei = sorted(roh.glob("praemienregionen-*.xlsx"))[-1]
    plz = lies_regionen(reg_datei)
    namen = {**FRUEHERE, **lies_versicherer(roh / "versicherer.xlsx")}
    print(f"  Regionen: {reg_datei.name}, {len(plz)} PLZ; Versicherer: {len(namen)} Namen")

    gueltige = {(e[1], str(e[2])) for v in plz.values() for e in v}
    df = df[[(k, r) in gueltige for k, r in zip(df["kt"], df["reg"])]]

    # Einschränkung je Zeile bestimmen
    def schl(r):
        m = einzug.get(r.jahr, {})
        return m.get((r.nr, r.kt, r.reg, r.tarif))
    df["ein"] = [schl(r) for r in df.itertuples()]

    for f in (OUT / "p").glob("*.json"):
        f.unlink()
    (OUT / "p").mkdir(parents=True, exist_ok=True)
    for (kt, reg), g in df.groupby(["kt", "reg"]):
        listen, idx = [], {}
        daten = {}
        g = g.sort_values("pr")
        for (jahr, akl, u, fr), h in g.groupby(["jahr", "akl", "u", "fr"]):
            zeilen, gesehen = [], set()
            for r in h.itertuples():
                e = -1
                if r.ein is not None:
                    if r.ein not in idx:
                        idx[r.ein] = len(listen)
                        listen.append(sorted(r.ein))
                    e = idx[r.ein]
                k = (r.nr, r.typ, e)
                if k in gesehen:  # pro Kasse/Modell/Gebiet nur das günstigste Produkt
                    continue
                gesehen.add(k)
                zeilen.append([r.nr, r.typ, round(float(r.pr), 2)] + ([e] if e >= 0 else []))
            daten.setdefault(str(jahr), {})[f"{akl}|{u}|{fr}"] = zeilen
        (OUT / "p" / f"{kt}-{reg}.json").write_text(
            json.dumps({"e": listen, "d": daten}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    jahre = sorted(int(j) for j in df["jahr"].unique())
    kassen = {nr: namen.get(nr, f"BAG-Nr. {nr}") for nr in sorted(df["nr"].unique(), key=int)}
    (OUT / "plz.json").write_text(json.dumps(plz, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (OUT / "meta.json").write_text(json.dumps({
        "demo": False, "stand": date.today().isoformat(), "jahre": jahre, "kassen": kassen,
        "aktiv": sorted(df.loc[df["jahr"] == jahre[-1], "nr"].unique(), key=int),
        "quelle": "BAG, Krankenversicherungsprämien (opendata.swiss); priminfo.admin.ch",
        "regionen": reg_datei.stem,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK: Jahre {jahre}, {len(kassen)} Kassen, {df.groupby(['kt', 'reg']).ngroups} Regionen")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roh", default=str(ROOT / "data-src" / "roh"))
    baue(Path(ap.parse_args().roh))


if __name__ == "__main__":
    main()
