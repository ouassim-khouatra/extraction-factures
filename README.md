# Extraction automatique et structuration de factures PDF

Système d'extraction automatique de factures PDF développé lors d'un stage Data & IA chez **Barid Media (Groupe Barid Al-Maghrib)**, Casablanca — juillet à août 2026.

L'objectif : transformer un flux de factures hétérogènes en données structurées et validées, sans qu'aucune facture erronée ne soit acceptée automatiquement. Une facture douteuse part en relecture humaine plutôt que d'être validée à tort.

## Résultats

Campagne d'évaluation sur un corpus synthétique de **550 factures** (500 cohérentes + 50 volontairement fautives, génération reproductible à graine fixe) :

| Métrique | Valeur | Seuil du cahier des charges |
|---|---|---|
| Faux-acceptés (factures erronées validées automatiquement) | **0 %** | 0 (obligatoire) |
| Détection des documents erronés | 100 % | ≥ 95 % |
| Traitement automatique (sans relecture) | **90,9 %** | ≥ 60 % |
| Exactitude des champs critiques (numéro, dates, ICE, totaux, devise) | 100 % | — |
| Latence médiane / p95 par document | 66 ms / 109 ms | ≤ 5 s |
| Débit | 19,8 documents/s | — |

Rapport complet dans `eval_resultats/`.

## Fonctionnement

```
PDF ──► PyMuPDF (texte natif)            ──┐
    └─► Tesseract OCR (scans)           ──┤
                                           ▼
                        Modèles Pydantic (schéma canonique)
                                           │
                                           ▼
                  Règles de dérivation et de validation métier
                              │                  │
                        valide ▼            douteuse ▼
                          SQLite            Interface Streamlit
                     + exports CSV/Excel    de relecture
```

- **Extraction** : PyMuPDF pour les PDF avec couche texte, Tesseract OCR pour les documents scannés.
- **Schéma canonique** : modèles Pydantic décrivant les champs d'une facture (numéro, dates, fournisseur, totaux HT/TVA/TTC, net à payer, devise), source de vérité unique.
- **Règles métier** : règles de dérivation (calcul des champs manquants) et de validation (cohérence des montants, dates, identifiants) avec arrondi et tolérance centralisés. Elles décident si une facture est acceptée automatiquement ou envoyée en relecture.
- **Persistance** : base SQLite via SQLAlchemy, exports CSV et Excel.
- **Relecture** : interface Streamlit présentant la file des factures à vérifier, pour correction et validation manuelles.
- **Évaluation** : harnais de tests mesurant exactitude par champ, faux-acceptés, taux d'automatisation et latence sur un corpus généré.

## Stack

Python · Pydantic · PyMuPDF · Tesseract OCR · SQLAlchemy · SQLite · Streamlit

Qualité : pytest, ruff, mypy, gestion des dépendances avec uv.

## Installation

```bash
git clone https://github.com/ouassim-khouatra/extraction-factures
cd extraction-factures
uv sync
```

Tesseract doit être installé sur la machine (`brew install tesseract` sur macOS, `sudo apt install tesseract-ocr` sur Debian/Ubuntu, installeur UB-Mannheim sur Windows).

## Utilisation

```bash
# 1. Générer le corpus synthétique (500 factures cohérentes + 50 fautives)
uv run python generer_corpus.py

# 2. Traiter un dossier de factures → factures.db + exports/
uv run python traiter.py --entree data/synthetique --base factures.db --exports exports

# 3. Ouvrir la file de relecture
uv run streamlit run relecture.py

# 4. Lancer une campagne d'évaluation → rapport daté dans eval_resultats/
uv run python evaluer.py --corpus data/synthetique

# Tests
uv run pytest -v
```

## Structure

```
extraction-factures/
├── src/extraction_factures/   # schéma Pydantic, règles, persistance, évaluation
├── tests/                     # tests pytest
├── eval_resultats/            # rapports de campagne
├── generer_corpus.py          # génération du corpus synthétique
├── traiter.py                 # pipeline d'extraction et de validation
├── relecture.py               # interface Streamlit de relecture
├── evaluer.py                 # harnais d'évaluation
├── demo_ocr.py                # démonstration OCR sur documents scannés
├── pyproject.toml / uv.lock
└── pytest.ini
```

## Auteur

Ouassim Khouatra — [LinkedIn](https://linkedin.com/in/ouassim-khouatra) · [GitHub](https://github.com/ouassim-khouatra)
