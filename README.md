# Prämienradar

Findet die günstigste Grundversicherung (OKP) für eine Schweizer Postleitzahl und zeigt, wie viel man gegenüber der eigenen Kasse spart – rückblickend, im aktuellen Prämienjahr und als Schätzung für die nächsten Jahre.

**Webseite:** https://christophejenzer-collab.github.io/praemienradar/

Grundlage sind die offiziellen Prämiendaten des Bundesamts für Gesundheit (BAG), publiziert auf [opendata.swiss](https://opendata.swiss/de/dataset/health-insurance-premiums).

## Aufbau

| Teil | Zweck |
|---|---|
| `docs/` | Webseite (GitHub Pages), rechnet komplett im Browser |
| `docs/data/` | aufbereitete Prämien als JSON, je Prämienregion eine Datei |
| `scripts/fetch_data.py` | lädt die BAG-Dateien über die CKAN-API von opendata.swiss |
| `scripts/build_data.py` | baut aus CSV/ZIP die JSON-Dateien (`--demo` für Testdaten) |
| `kk_vergleich.py` | dieselbe Auswertung als Kommandozeilen-Tool |
| `.github/workflows/daten-update.yml` | aktualisiert die Daten jeden Oktober automatisch |

## Echte Daten einspielen

1. Das BAG-Verzeichnis der Prämienregionen (Gemeinden/PLZ → Region) als `data-src/Praemienregionen.xlsx` committen – oder die Download-URL als Repository-Variable `REGIONEN_URL` hinterlegen (Settings → Secrets and variables → Actions → Variables).
2. Optional `data-src/Versicherer.csv` mit den Spalten `Versicherer;Name` ergänzen, damit statt der BAG-Nummer der Kassenname erscheint.
3. Im Tab **Actions** den Workflow «Prämiendaten aktualisieren» manuell starten.

Bis dahin läuft die Seite im Demo-Modus mit erfundenen Zahlen.

## Lokal

```bash
pip install pandas openpyxl
python scripts/build_data.py --demo        # oder ohne --demo mit echten Daten
cd docs && python -m http.server           # http://localhost:8000

python kk_vergleich.py 3653 --alter 45 --franchise 2500 --unfall nein --kasse CSS --daten data-src/praemien --regionen data-src/Praemienregionen.xlsx
```

## Grenzen

- Die mögliche Ersparnis der Vorjahre unterstellt einen jährlichen Wechsel zur günstigsten Kasse (Obergrenze).
- Die Schätzung schreibt das durchschnittliche Wachstum fort; sie ist keine Prognose des BAG.
- Die heutige Regionenzuteilung wird auf alle Jahre angewendet.
- Prämienverbilligung und Zusatzversicherungen sind nicht berücksichtigt.

Keine Beratung. Massgebend sind die Prämien der Versicherer bzw. [priminfo.admin.ch](https://www.priminfo.admin.ch).
