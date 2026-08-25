"""Tests de la logique de relecture (EF-25 / EF-33), sans navigateur."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from generateur.synthetique import generer_corpus
from persistance.base import Base, DocumentDB, JournalAuditDB
from persistance.pipeline import traiter_dossier
from persistance.logique_relecture import appliquer_corrections, documents_a_relire


@pytest.fixture()
def base_prete(tmp_path) -> str:
    corpus = tmp_path / "corpus"
    generer_corpus(corpus, nb_coherentes=3, nb_fautives=2, graine=55)
    url = f"sqlite:///{tmp_path / 'test.db'}"
    traiter_dossier(corpus, url)
    return url


def test_correction_journalisee_et_document_valide(base_prete):
    engine = create_engine(base_prete)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        en_attente = documents_a_relire(session)
        assert len(en_attente) == 2  # les deux fautes injectees

        doc = en_attente[0]
        ancienne_valeur = doc.facture.total_ttc
        corriges = appliquer_corrections(
            session, doc.facture.id,
            {"total_ttc": "999.99", "devise": doc.facture.devise or ""},
            auteur="amine",
        )

        assert corriges == ["total_ttc"]  # la devise inchangee n'est pas journalisee
        assert doc.statut == "valide"
        assert doc.facture.total_ttc == "999.99"

        # EF-25 : champ, avant, apres, auteur — tout est au journal.
        entree = session.scalar(
            select(JournalAuditDB).where(JournalAuditDB.evenement == "correction")
        )
        detail = json.loads(entree.detail)
        assert detail == {
            "champ": "total_ttc", "avant": ancienne_valeur,
            "apres": "999.99", "auteur": "amine",
        }
        # Et il ne reste plus qu'un document en attente.
        assert len(documents_a_relire(session)) == 1
