#!/usr/bin/env python3
"""
fetch_data.py – lädt die BAG-Prämiendaten von opendata.swiss (CKAN-API) nach data-src/praemien/.
Optional: Umgebungsvariable REGIONEN_URL zeigt auf das BAG-Verzeichnis der Prämienregionen.
Läuft in der GitHub Action (dort ist Internet frei), lokal genauso.
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZIEL = ROOT / "data-src" / "praemien"
API = "https://ckan.opendata.swiss/api/3/action/package_show?id=health-insurance-premiums"
MIN_JAHR = 2018


def lade(url: str, pfad: Path):
    print(f"  ↓ {pfad.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "praemienradar"})
    with urllib.request.urlopen(req, timeout=120) as r:
        pfad.write_bytes(r.read())


def main():
    ZIEL.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(API, timeout=60) as r:
        res = json.load(r)["result"]["resources"]

    gewaehlt = []
    for x in res:
        url = x.get("url") or x.get("download_url") or ""
        name = (x.get("name") or {})
        name = name.get("de") or name.get("en") or next(iter(name.values()), "") if isinstance(name, dict) else str(name)
        datei = name or url.rsplit("/", 1)[-1]
        if re.fullmatch(r"Pr(ä|ae)mien_CH\.csv", datei, re.I):
            gewaehlt.append((url, "Prämien_CH.csv"))
        m = re.match(r"Archiv_Praemien_(\d{4})\.zip", datei, re.I)
        if m and int(m.group(1)) >= MIN_JAHR:
            gewaehlt.append((url, datei))
    if not gewaehlt:
        sys.exit("Keine passenden Ressourcen gefunden. Vorhanden: " +
                 ", ".join(str(x.get("name")) for x in res))
    print(f"Lade {len(gewaehlt)} Dateien nach {ZIEL}")
    for url, datei in gewaehlt:
        lade(url, ZIEL / datei)

    reg_url = os.environ.get("REGIONEN_URL", "").strip()
    if reg_url:
        endung = ".xlsx" if ".xls" in reg_url.lower() else ".csv"
        lade(reg_url, ROOT / "data-src" / f"Praemienregionen{endung}")


if __name__ == "__main__":
    main()
