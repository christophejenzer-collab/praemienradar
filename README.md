# Prämienradar

Findet die günstigste Grundversicherung (OKP) für eine Schweizer Postleitzahl und zeigt, wie viel man gegenüber der eigenen Kasse spart – rückblickend, im aktuellen Prämienjahr und als Schätzung für die nächsten Jahre.

**Webseite:** https://christophejenzer-collab.github.io/praemienradar/

Grundlage sind die offiziellen Prämiendaten des Bundesamts für Gesundheit (BAG), publiziert auf [opendata.swiss](https://opendata.swiss/de/dataset/health-insurance-premiums).

## Daten

| Quelle | Inhalt |
|---|---|
| [BAG, Krankenversicherungsprämien](https://opendata.swiss/de/dataset/health-insurance-premiums) | alle genehmigten OKP-Prämien, hier 2018–2027, inkl. eingeschränkter Tätigkeitsgebiete |
| [priminfo.admin.ch](https://www.priminfo.admin.ch/de/downloads/aktuell) | Prämienregionen nach Gemeinde/PLZ, Verzeichnis der zugelassenen Versicherer |

Geprüft: Die günstigste Prämie 2027 (Erwachsene, Franchise 300, Standard, mit Unfall) stimmt in allen 42 Prämienregionen mit einer unabhängigen Auswertung überein.

## Aufbau

| Teil | Zweck |
|---|---|
| `docs/` | Webseite (GitHub Pages), rechnet komplett im Browser |
| `docs/data/` | aufbereitete Prämien als JSON, je Prämienregion eine Datei |
| `scripts/build_data.py` | baut aus den Rohdaten die JSON-Dateien |
| `kk_vergleich.py` | dieselbe Auswertung als Kommandozeilen-Tool (nur Python, keine Pakete) |
| `.github/workflows/rohdaten.yml` | lädt jeden Oktober die BAG-Dateien in den Branch `rohdaten` |
| `.github/workflows/daten-update.yml` | baut danach die Webseiten-Daten neu und committet sie |

## Funktionen

- PLZ eingeben (Standard 3600 Thun) oder «Meinen Standort verwenden» (PLZ über den Geodienst des Bundes, api3.geo.admin.ch)
- bis 5 Personen: Alter, Franchise, Unfalldeckung, heutige Kasse und Modell je Person
- Vergleich **heute** / **einzeln** (jede Person bei der für sie günstigsten Kasse) / **eine Kasse für alle** – die Differenz ist der Preis für weniger Admin-Aufwand
- Geschwisterrabatte aus den BAG-Daten: K3 (ab dem 3. Kind), K4 (ab 2 Kindern für alle), K5 (ab 3 Kindern für alle), nur bei derselben Kasse
- Verlauf 2018 bis heute und Schätzung für 3 Jahre; Ergebnis als Link teilbar

## Lokal

```bash
python kk_vergleich.py                                   # PLZ 3600, eine Person
python kk_vergleich.py 3653 --alter 45 --franchise 2500 --unfall nein --kasse CSS
python kk_vergleich.py 3653 --person "45,2500,nein,CSS" --person "43,2500,nein,CSS" \
       --person "12,0,ja,CSS" --person "9,0,ja,CSS" --person "6,0,ja,CSS"
cd docs && python -m http.server                         # Webseite lokal: http://localhost:8000

# Daten selbst neu bauen
git fetch origin rohdaten && mkdir -p data-src/roh && git archive origin/rohdaten | tar -x -C data-src/roh
pip install pandas openpyxl && python scripts/build_data.py
```

## Grenzen

- Die mögliche Ersparnis der Vorjahre unterstellt einen jährlichen Wechsel zur günstigsten Kasse (Obergrenze).
- Die Schätzung schreibt das durchschnittliche Wachstum fort; sie ist keine Prognose des BAG.
- Die heutige Regionenzuteilung wird auf alle Jahre angewendet.
- Modelle in drei Gruppen (Standard, Hausarzt/HMO, Telmed/andere), weil das BAG die Codes 2027 geändert hat.
- 2024: Tarife Januar–August (das BAG führt für 2024 zwei Stände).
- Familie «einzeln»: Erwachsene je bei ihrer günstigsten Kasse; Kinder entweder je einzeln oder alle zusammen bei einer Kasse (Geschwisterrabatt). Als «3. Kind» gilt das jüngste.
- Prämienverbilligung, Zusatzversicherungen und deren Familienrabatte sind nicht berücksichtigt.

Keine Beratung. Massgebend sind die Prämien der Versicherer bzw. [priminfo.admin.ch](https://www.priminfo.admin.ch).
