"""Tests du lecteur PDF natif : la boucle complete generateur -> extraction.

Le principe : on fabrique des factures avec le generateur (dont on connait
la verite terrain par construction), on les relit avec le lecteur natif,
et l'extraction doit retrouver les champs critiques (EF-23) a l'identique.
C'est la premiere mesure d'exactitude reelle du projet.
"""

import json
from pathlib import Path

import pymupdf
import pytest

from extraction.lecteur_natif import detecter_couche_texte, extraire_facture_native
from generateur.synthetique import generer_corpus
from regles.derivation import appliquer_derivations
from regles.validation import a_des_erreurs, valider
from schema.modeles import Facture

CHAMPS_CRITIQUES_SIMPLES = [
    "numero_facture", "date_emission", "devise",
    "total_ht", "total_tva", "total_ttc", "net_a_payer",
]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    dossier = tmp_path_factory.mktemp("corpus")
    generer_corpus(dossier, nb_coherentes=15, nb_fautives=0, graine=11)
    return dossier / "coherentes"


def _valeur(champ):
    return None if champ is None else champ.valeur


def test_detection_couche_texte(corpus, tmp_path):
    un_pdf = sorted(corpus.glob("*.pdf"))[0]
    assert detecter_couche_texte(un_pdf) is True

    # Un PDF sans texte (page vierge) doit partir vers la chaine visuelle.
    vide = tmp_path / "scan_simule.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(vide)
    assert detecter_couche_texte(vide) is False


def test_extraction_retrouve_les_champs_critiques(corpus):
    for chemin_json in sorted(corpus.glob("*.json")):
        attendu = Facture.model_validate(
            json.loads(chemin_json.read_text(encoding="utf-8"))["facture"]
        )
        extrait = extraire_facture_native(chemin_json.with_suffix(".pdf"))

        for nom in CHAMPS_CRITIQUES_SIMPLES:
            assert _valeur(getattr(extrait, nom)) == _valeur(getattr(attendu, nom)), (
                f"{chemin_json.stem} : champ {nom}"
            )
        assert _valeur(extrait.type_document) == _valeur(attendu.type_document)
        assert _valeur(extrait.fournisseur.nom) == _valeur(attendu.fournisseur.nom)
        assert _valeur(extrait.fournisseur.ice) == _valeur(attendu.fournisseur.ice)
        assert len(extrait.lignes) == len(attendu.lignes)


def test_extraction_puis_regles_zero_erreur(corpus):
    """La boucle complete : PDF -> extraction -> derivations -> validations.
    Sur des factures coherentes, le filet ne doit rien signaler en erreur."""
    for pdf in sorted(corpus.glob("*.pdf")):
        f = extraire_facture_native(pdf)
        appliquer_derivations(f)
        anomalies = valider(f)
        assert not a_des_erreurs(anomalies), f"{pdf.stem} : {anomalies}"
