"""Harnais d'evaluation (CDC section 9 — livrable n°4).

Une seule fonction qui prend un corpus etiquete (PDF + JSON de verite
terrain) et produit le tableau de metriques du CDC :

- exactitude par champ critique (EF-23), tolerance +/- 0,01 sur les montants ;
- taux de documents parfaits (tous les champs critiques corrects) ;
- taux de traitement automatique (documents auto-acceptes) ;
- TAUX DE FAUX-ACCEPTES — la metrique principale, qui doit valoir ZERO :
  part des documents auto-acceptes comportant au moins une erreur ;
- taux de detection : part des documents reellement errones envoyes en
  relecture ;
- debit et latence.

Regle du CDC scrupuleusement suivie : "Aucune mesure annoncee sans la
commande qui la reproduit" — d'ou le script evaluer.py et le fichier de
resultats date ecrit a chaque campagne.
"""

import json
import statistics
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from extraction.lecteur_natif import extraire_facture_native
from regles.commun import egaux
from regles.derivation import appliquer_derivations
from regles.validation import a_des_erreurs, valider
from schema.modeles import Champ, Facture

# Champs critiques (EF-23). Chemin d'acces -> montant (tolerance) ou exact.
CHAMPS_CRITIQUES: list[tuple[str, bool]] = [
    ("numero_facture", False),
    ("date_emission", False),
    ("fournisseur.ice", False),
    ("fournisseur.nom", False),
    ("total_ht", True),
    ("total_tva", True),
    ("total_ttc", True),
    ("net_a_payer", True),
    ("devise", False),
]


def _champ(f: Facture, chemin: str) -> Optional[Champ]:
    objet = f
    for morceau in chemin.split("."):
        if objet is None:
            return None
        objet = getattr(objet, morceau)
    return objet


def _valeurs_egales(a, b, est_montant: bool) -> bool:
    if est_montant and isinstance(a, Decimal) and isinstance(b, Decimal):
        return egaux(a, b, nb_operandes=1)
    return a == b


def evaluer_document(chemin_pdf: Path, etiquette: dict) -> dict:
    """Evalue un document : extraction chronometree + comparaison + decision."""
    attendu = Facture.model_validate(etiquette["facture"])
    faute = etiquette.get("faute")

    debut = time.perf_counter()
    extrait = extraire_facture_native(chemin_pdf)
    duree = time.perf_counter() - debut

    appliquer_derivations(extrait)
    anomalies = valider(extrait)
    # Porte d'auto-acceptation (EF-22, version lecture unique) : aucune
    # regle de severite erreur. La concordance de lectures multiples
    # viendra avec la double lecture (extension documentee).
    auto_accepte = not a_des_erreurs(anomalies)

    champs: dict[str, Optional[bool]] = {}
    for chemin, est_montant in CHAMPS_CRITIQUES:
        champ_attendu = _champ(attendu, chemin)
        if champ_attendu is None or champ_attendu.valeur is None:
            champs[chemin] = None  # absent de la verite terrain : hors mesure
            continue
        champ_extrait = _champ(extrait, chemin)
        champs[chemin] = (
            champ_extrait is not None
            and champ_extrait.valeur is not None
            and _valeurs_egales(champ_extrait.valeur, champ_attendu.valeur, est_montant)
        )

    mesures = [v for v in champs.values() if v is not None]
    parfait = all(mesures) if mesures else True
    erreur_reelle = (faute is not None) or (not parfait)

    return {
        "document": chemin_pdf.stem,
        "faute": faute,
        "duree_s": duree,
        "auto_accepte": auto_accepte,
        "parfait": parfait,
        "erreur_reelle": erreur_reelle,
        "faux_accepte": auto_accepte and erreur_reelle,
        "champs": champs,
    }


def evaluer_corpus(dossier: Path) -> dict:
    """Evalue tous les couples (PDF, JSON) de `dossier` (recursif)."""
    resultats = []
    for chemin_json in sorted(dossier.rglob("*.json")):
        chemin_pdf = chemin_json.with_suffix(".pdf")
        if not chemin_pdf.exists():
            continue
        etiquette = json.loads(chemin_json.read_text(encoding="utf-8"))
        resultats.append(evaluer_document(chemin_pdf, etiquette))

    n = len(resultats)
    if n == 0:
        raise ValueError(f"Aucun couple PDF+JSON trouve dans {dossier}")

    exactitude: dict[str, tuple[int, int]] = {}
    for chemin, _ in CHAMPS_CRITIQUES:
        mesures = [r["champs"][chemin] for r in resultats if r["champs"][chemin] is not None]
        exactitude[chemin] = (sum(mesures), len(mesures))

    auto_acceptes = [r for r in resultats if r["auto_accepte"]]
    errones = [r for r in resultats if r["erreur_reelle"]]
    faux_acceptes = [r for r in resultats if r["faux_accepte"]]
    durees = sorted(r["duree_s"] for r in resultats)

    return {
        "horodatage": datetime.now().isoformat(timespec="seconds"),
        "corpus": str(dossier),
        "nb_documents": n,
        "exactitude_par_champ": {
            champ: (ok, total, (ok / total) if total else None)
            for champ, (ok, total) in exactitude.items()
        },
        "taux_documents_parfaits": sum(r["parfait"] for r in resultats) / n,
        "taux_traitement_automatique": len(auto_acceptes) / n,
        "nb_faux_acceptes": len(faux_acceptes),
        "taux_faux_acceptes": (len(faux_acceptes) / len(auto_acceptes)) if auto_acceptes else 0.0,
        "taux_detection": (
            sum(1 for r in errones if not r["auto_accepte"]) / len(errones)
        ) if errones else None,
        "latence_mediane_s": statistics.median(durees),
        "latence_p95_s": durees[min(n - 1, int(0.95 * n))],
        "debit_docs_par_s": n / sum(durees) if sum(durees) else None,
        "faux_acceptes_detail": [r["document"] for r in faux_acceptes],
    }


def formater_rapport(m: dict) -> str:
    """Tableau lisible (console + fichier Markdown date)."""
    lignes = [
        f"# Campagne d'evaluation — {m['horodatage']}",
        "",
        f"Corpus : `{m['corpus']}` — {m['nb_documents']} documents",
        "",
        "## Exactitude par champ critique (EF-23)",
        "",
        "| Champ | Corrects | Mesures | Exactitude |",
        "|---|---|---|---|",
    ]
    for champ, (ok, total, taux) in m["exactitude_par_champ"].items():
        affiche = f"{taux:.1%}" if taux is not None else "n/a"
        lignes.append(f"| {champ} | {ok} | {total} | {affiche} |")
    detection = f"{m['taux_detection']:.1%}" if m["taux_detection"] is not None else "n/a"
    lignes += [
        "",
        "## Metriques globales",
        "",
        "| Metrique | Valeur | Seuil CDC |",
        "|---|---|---|",
        f"| Taux de faux-acceptes | **{m['taux_faux_acceptes']:.1%}"
        f" ({m['nb_faux_acceptes']} doc)** | 0 (obligatoire) |",
        f"| Taux de detection des documents errones | {detection} | >= 95% |",
        f"| Taux de documents parfaits | {m['taux_documents_parfaits']:.1%} | - |",
        f"| Taux de traitement automatique | {m['taux_traitement_automatique']:.1%} | >= 60% (souhaite) |",
        f"| Latence mediane / p95 | {m['latence_mediane_s'] * 1000:.0f} ms"
        f" / {m['latence_p95_s'] * 1000:.0f} ms | <= 5 s (PDF natif) |",
        f"| Debit | {m['debit_docs_par_s']:.1f} docs/s | - |",
    ]
    if m["faux_acceptes_detail"]:
        lignes += ["", "## FAUX-ACCEPTES A CORRIGER (defaut bloquant)", ""]
        lignes += [f"- {d}" for d in m["faux_acceptes_detail"]]
    return "\n".join(lignes)


def campagne(dossier_corpus: Path, dossier_resultats: Path) -> tuple[dict, Path]:
    """Une campagne complete : mesure + rapport date sur disque."""
    metriques = evaluer_corpus(dossier_corpus)
    dossier_resultats.mkdir(parents=True, exist_ok=True)
    horodatage = metriques["horodatage"].replace(":", "-")
    chemin = dossier_resultats / f"campagne_{horodatage}.md"
    chemin.write_text(formater_rapport(metriques), encoding="utf-8")
    return metriques, chemin
