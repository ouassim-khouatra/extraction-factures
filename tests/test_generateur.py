"""Tests du generateur synthetique (CDC 8.2 / 8.3).

La propriete centrale testee ici : le generateur et le filet de validation
se controlent MUTUELLEMENT. Toute facture generee coherente passe sans
erreur ; toute facture a faute injectee est attrapee — a 100%, car
"un filet qui en laisse passer un seul constitue un defaut bloquant".
"""

import json
import random
from pathlib import Path

from generateur.synthetique import (
    FAUTES,
    facture_coherente,
    generer_corpus,
    injecter_faute,
)
from regles.validation import a_des_erreurs, valider
from schema.modeles import Facture


def test_les_factures_coherentes_passent_le_filet():
    rng = random.Random(1)
    for i in range(40):
        f, _ = facture_coherente(rng, i)
        assert not a_des_erreurs(valider(f)), f"facture {i} incoherente"


def test_chaque_type_de_faute_est_detecte():
    rng = random.Random(2)
    for faute in FAUTES:
        detectee = False
        for i in range(30):  # on cherche une facture compatible avec la faute
            f, _ = facture_coherente(rng, 100 + i)
            appliquee = injecter_faute(f, rng, faute=faute)
            if appliquee != faute:
                continue
            assert a_des_erreurs(valider(f)), f"faute {faute} non detectee"
            detectee = True
            break
        assert detectee, f"impossible de tester la faute {faute}"


def test_generation_complete_pdf_et_verite_terrain(tmp_path: Path):
    bilan = generer_corpus(tmp_path, nb_coherentes=6, nb_fautives=4, graine=7)
    assert bilan == {"coherentes": 6, "fautives": 4}

    pdfs = sorted(tmp_path.glob("*/*.pdf"))
    jsons = sorted(tmp_path.glob("*/*.json"))
    assert len(pdfs) == 10 and len(jsons) == 10
    assert all(p.stat().st_size > 1000 for p in pdfs)  # de vrais PDF

    # La verite terrain suit exactement le schema : elle se recharge telle quelle.
    for chemin in jsons:
        etiquette = json.loads(chemin.read_text(encoding="utf-8"))
        f = Facture.model_validate(etiquette["facture"])
        erreurs = a_des_erreurs(valider(f))
        if etiquette["faute"] is None:
            assert not erreurs
        else:
            assert erreurs


def test_reproductibilite_meme_graine_memes_factures(tmp_path: Path):
    """ENF-04 : a entree identique, sortie identique."""
    a, b = tmp_path / "a", tmp_path / "b"
    generer_corpus(a, nb_coherentes=3, nb_fautives=1, graine=99)
    generer_corpus(b, nb_coherentes=3, nb_fautives=1, graine=99)
    contenus_a = sorted(p.read_text(encoding="utf-8") for p in a.glob("*/*.json"))
    contenus_b = sorted(p.read_text(encoding="utf-8") for p in b.glob("*/*.json"))
    assert contenus_a == contenus_b
