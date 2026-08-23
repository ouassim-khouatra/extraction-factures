# Semaine 2 — Schéma canonique, dérivation, validation

Zéro GPU nécessaire. Tout tourne sur ta machine actuelle.

## Où mettre les fichiers

```
extraction-factures/
├── pytest.ini                  ← config pytest (fourni)
├── src/
│   ├── schema/
│   │   ├── __init__.py         ← fichier vide (fourni)
│   │   └── modeles.py          ← LE schéma — source de vérité unique
│   └── regles/
│       ├── __init__.py         ← fichier vide (fourni)
│       ├── commun.py           ← arrondi + tolérance + present() — UN seul endroit
│       ├── derivation.py       ← règles RD (2 exemples, 6 à écrire)
│       └── validation.py       ← règles RV (3 exemples, 9 à écrire)
└── tests/
    └── test_semaine2.py        ← 11 tests qui passent — ta base de départ
```

## Installer et lancer

```bash
uv add pydantic
uv add --dev pytest ruff mypy
uv run pytest -v
```

Attendu : `11 passed`. Si les imports échouent, vérifie que `pytest.ini`
est bien à la racine (c'est lui qui ajoute `src/` au chemin Python).

## Ce qui est implémenté (à lire AVANT d'écrire quoi que ce soit)

| Module | Fait | Ce que ça t'apprend |
|---|---|---|
| `modeles.py` | Schéma complet Annexe A | Tous champs optionnels ; `Champ[T]` = valeur + provenance |
| `commun.py` | `arrondi`, `egaux`, `present`, barème TVA | Conventions numériques en un seul endroit, testées |
| `derivation.py` | RD-01, RD-05 + boucle point fixe | Ne jamais écraser un champ lu ; "termes présents seulement" |
| `validation.py` | RV-06, RV-08 (erreur), RV-11 (avertissement) | Règles conditionnelles ; les maths bloquent, les formats avertissent |

## Ton travail de la semaine — méthode imposée : test d'abord

Pour CHAQUE règle : 1) écris le test avec un JSON à la main dans
`tests/`, 2) lance pytest → il échoue, 3) écris la règle en imitant les
exemples, 4) pytest → il passe, 5) commit.

**Dérivations à écrire** (énoncés exacts : tableau 5.5 du CDC)
- [ ] RD-02 — HT + taux → TVA puis TTC
- [ ] RD-03 — HT + TVA → taux (normalisé par RD-08)
- [ ] RD-08 — aligner un taux calculé sur le barème si écart < 0,5 pt (utilitaire)
- [ ] RD-04 — lignes → bandes de TVA → totaux (la plus riche, garde-la pour la fin)
- [ ] RD-06 — TTC + acompte → net à payer
- [ ] RD-07 — qté × PU − remise → montant HT ligne

**Validations à écrire** (énoncés exacts : tableau 5.6 du CDC)
- [ ] RV-01 — cohérence de chaque ligne (erreur)
- [ ] RV-02 — somme des lignes = total HT, remise/port pris en compte (erreur)
- [ ] RV-03 — document valorisé TTC seul (erreur)
- [ ] RV-04 — base × taux = TVA par bande (erreur)
- [ ] RV-05 — somme des bandes = total TVA (erreur)
- [ ] RV-07 — TTC − acompte − escompte = net à payer (erreur)
- [ ] RV-09 — ICE = 15 chiffres (erreur)
- [ ] RV-10 — Luhn SIRET, format TVA intra (AVERTISSEMENT, pas erreur !)
- [ ] RV-12 — devise unique (avertissement)

Puis ajoute un test par cas dur de la section 4.1 du CDC (multi-taux,
remise globale, acompte, avoir…) : c'est ta preuve que le schéma
"en surensemble" absorbe vraiment la variabilité.

## Les 5 idées à comprendre (pas juste copier)

1. **`Decimal`, jamais `float`** pour l'argent. `0.1 + 0.2 != 0.3` en
   float — avec une tolérance à ±0,01, les floats créent des faux
   positifs de validation impossibles à déboguer.
2. **`Champ[T]`** : chaque valeur porte sa provenance. Un HT dérivé par
   RD-01 ne pourra jamais être confondu avec un HT lu — c'est l'exigence
   ENF-03 et la section 4.b du CDC.
3. **`present()`** : la brique des règles conditionnelles. Une règle qui
   ne vérifie pas `present()` sur ses entrées est fausse par construction.
4. **Une dérivation n'écrase JAMAIS un champ lu.** Si la valeur est lue
   et dérivable → on compare (validation), on ne recalcule pas.
5. **Arrondi et tolérance vivent dans `commun.py` et nulle part
   ailleurs.** Le jour où le comptable change la convention, tu modifies
   une ligne, pas douze règles.

## Fin de semaine — livrable CDC

Modules schéma + dérivation + validation éprouvés sur JSON à la main,
couverture ≥ 70 % sur ces modules (`uv add --dev pytest-cov` puis
`uv run pytest --cov=src`), et la convention de signe des avoirs figée
par écrit avec le comptable.
