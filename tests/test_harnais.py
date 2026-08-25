"""Tests du harnais d'evaluation (CDC section 9)."""

from pathlib import Path

import pytest

from evaluation.harnais import campagne, evaluer_corpus
from generateur.synthetique import generer_corpus


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    dossier = tmp_path_factory.mktemp("corpus_eval")
    generer_corpus(dossier, nb_coherentes=10, nb_fautives=6, graine=21)
    return dossier


def test_metriques_sur_corpus_synthetique(corpus):
    m = evaluer_corpus(corpus)

    assert m["nb_documents"] == 16
    # LA metrique principale du CDC : zero faux-accepte.
    assert m["nb_faux_acceptes"] == 0
    assert m["taux_faux_acceptes"] == 0.0
    # Toutes les factures a faute injectee partent en relecture.
    assert m["taux_detection"] == 1.0
    # Chaine native sur corpus synthetique : extraction parfaite attendue.
    for champ, (ok, total, taux) in m["exactitude_par_champ"].items():
        if total:
            assert taux == 1.0, f"exactitude imparfaite sur {champ}"


def test_campagne_ecrit_un_rapport_date(corpus, tmp_path):
    metriques, chemin = campagne(corpus, tmp_path / "resultats")
    assert chemin.exists()
    contenu = chemin.read_text(encoding="utf-8")
    assert "faux-acceptes" in contenu.lower()
    assert "Exactitude par champ" in contenu
