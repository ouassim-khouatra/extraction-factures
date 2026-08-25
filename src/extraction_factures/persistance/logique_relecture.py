"""Logique metier de l'ecran de relecture (CDC 5.9, EF-25 / EF-33).

Separee de l'interface Streamlit pour etre testable sans navigateur :
- lister les documents en attente de relecture ;
- appliquer les corrections d'un relecteur et journaliser CHAQUE champ
  modifie (champ, ancienne valeur, nouvelle valeur, auteur, horodatage
  — exigence EF-25), puis passer le document a l'etat `valide`.

Le journal des corrections vit dans la table journal_audit (ajout seul,
ENF-07) : c'est la piste d'audit, pas un fichier de log applicatif —
la contrainte ENF-02 (pas de donnees en clair dans les logs) reste
respectee.
"""

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistance.base import DocumentDB, FactureDB, JournalAuditDB

# Champs de l'en-tete corrigeables a l'ecran (colonnes de FactureDB).
CHAMPS_EDITABLES = [
    "numero_facture", "type_document", "date_emission", "date_echeance",
    "devise", "ice_fournisseur", "total_ht", "total_remise", "total_tva",
    "total_ttc", "timbre_fiscal", "acompte", "net_a_payer",
]


def documents_a_relire(session: Session) -> list[DocumentDB]:
    return list(session.scalars(
        select(DocumentDB).where(DocumentDB.statut == "a_relire").order_by(DocumentDB.id)
    ))


def compteurs_statuts(session: Session) -> dict[str, int]:
    compte: dict[str, int] = {}
    for doc in session.scalars(select(DocumentDB)):
        compte[doc.statut] = compte.get(doc.statut, 0) + 1
    return compte


def appliquer_corrections(
    session: Session,
    facture_id: int,
    modifications: dict[str, Optional[str]],
    auteur: str,
) -> list[str]:
    """Applique les corrections, journalise chaque changement (EF-25),
    valide le document (EF-33). Retourne la liste des champs corriges."""
    facture = session.get(FactureDB, facture_id)
    if facture is None:
        raise ValueError(f"Facture {facture_id} introuvable")

    corriges: list[str] = []
    for champ, nouvelle in modifications.items():
        if champ not in CHAMPS_EDITABLES:
            continue
        nouvelle = (nouvelle or "").strip() or None
        ancienne = getattr(facture, champ)
        if nouvelle == ancienne:
            continue
        setattr(facture, champ, nouvelle)
        corriges.append(champ)
        session.add(JournalAuditDB(
            evenement="correction",
            document_sha256=facture.document.sha256,
            detail=json.dumps(
                {"champ": champ, "avant": ancienne, "apres": nouvelle, "auteur": auteur},
                ensure_ascii=False,
            ),
        ))

    facture.document.statut = "valide"
    session.add(JournalAuditDB(
        evenement="valide", document_sha256=facture.document.sha256, detail=auteur,
    ))
    session.commit()
    return corriges
