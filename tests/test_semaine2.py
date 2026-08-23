"""Tests de la semaine 2 — schema, derivation, validation.

Exactement ce que demande le CDC : eprouver les modules sur des JSON
ecrits a la main, sans modele, sans GPU. Chaque cas dur de la section 4.1
doit finir par avoir son test ici.

Lancer :  uv run pytest -v
"""

from datetime import date
from decimal import Decimal

from regles.commun import arrondi, egaux
from regles.derivation import appliquer_derivations, rd_01
from regles.validation import Severite, a_des_erreurs, valider
from schema.modeles import (
    BandeTVA,
    Champ,
    Facture,
    Source,
    TypeDocument,
)

D = Decimal  # raccourci de lisibilite


# ---------------------------------------------------------------------------
# Conventions numeriques (le CDC exige qu'elles soient testees)
# ---------------------------------------------------------------------------


def test_arrondi_commercial():
    assert arrondi(D("10.005")) == D("10.01")  # 0,5 arrondit vers le haut
    assert arrondi(D("10.004")) == D("10.00")


def test_tolerance_par_operande():
    # 1 operande : +/- 0,01
    assert egaux(D("100.00"), D("100.01"), nb_operandes=1)
    assert not egaux(D("100.00"), D("100.02"), nb_operandes=1)
    # 12 operandes (12 lignes) : +/- 0,12
    assert egaux(D("100.00"), D("100.12"), nb_operandes=12)
    assert not egaux(D("100.00"), D("100.13"), nb_operandes=12)


# ---------------------------------------------------------------------------
# Cas 4.1 : facture affichant uniquement le TTC
# ---------------------------------------------------------------------------


def test_ttc_seul_derive_ht_et_tva():
    f = Facture(
        total_ttc=Champ.lu(D("120.00"), brute="120,00 DH"),
        bandes_tva=[BandeTVA(taux=Champ.lu(D("20")))],
    )
    appliquees = appliquer_derivations(f)

    assert "rd_01" in appliquees
    assert f.total_ht is not None and f.total_ht.valeur == D("100.00")
    assert f.total_tva is not None and f.total_tva.valeur == D("20.00")
    # Un champ derive ne doit JAMAIS ressembler a un champ lu :
    assert f.total_ht.source is Source.DERIVE
    assert f.total_ht.regle == "RD-01"
    # Et la facture ainsi completee est coherente :
    assert valider(f) == []


def test_ttc_seul_sans_taux_identifiable_reste_vide_sans_erreur():
    """Pas de taux -> HT reste vide, et ce n'est PAS une anomalie.
    C'est le principe central du CDC : l'absence n'est jamais une erreur."""
    f = Facture(total_ttc=Champ.lu(D("120.00")))
    appliquer_derivations(f)

    assert f.total_ht is None
    assert valider(f) == []


def test_derivation_ne_touche_jamais_un_champ_lu():
    """Si HT a ete LU, rd_01 ne s'applique pas — meme si HT est derivable.
    (La coherence HT/TTC releve alors de la validation, pas de la derivation.)"""
    f = Facture(
        total_ht=Champ.lu(D("999.99")),  # valeur lue, volontairement fausse
        total_ttc=Champ.lu(D("120.00")),
        bandes_tva=[BandeTVA(taux=Champ.lu(D("20")))],
    )
    assert rd_01(f) is False
    assert f.total_ht is not None
    assert f.total_ht.valeur == D("999.99")  # intacte
    assert f.total_ht.source is Source.LU


# ---------------------------------------------------------------------------
# Cas 4.1 : bon de livraison sans prix
# ---------------------------------------------------------------------------


def test_bl_sans_montants_aucune_regle_ne_se_declenche():
    f = Facture(
        type_document=Champ.lu(TypeDocument.BON_DE_LIVRAISON),
        numero_facture=Champ.lu("BL-2026-042"),
    )
    assert appliquer_derivations(f) == []
    assert valider(f) == []  # zero anomalie : l'absence n'est pas une erreur


# ---------------------------------------------------------------------------
# Validation : les maths bloquent
# ---------------------------------------------------------------------------


def test_rv06_total_incoherent_est_une_erreur():
    f = Facture(
        total_ht=Champ.lu(D("100.00")),
        total_tva=Champ.lu(D("20.00")),
        total_ttc=Champ.lu(D("125.00")),  # faux : devrait etre 120.00
    )
    anomalies = valider(f)

    assert len(anomalies) == 1
    assert anomalies[0].regle == "RV-06"
    assert anomalies[0].severite is Severite.ERREUR
    assert a_des_erreurs(anomalies)  # -> interdit l'auto-acceptation


def test_rv06_avec_port_et_timbre():
    """Motif 'termes presents seulement' : 100 + 20 + 30 (port) + 0.25 (timbre)."""
    f = Facture(
        total_ht=Champ.lu(D("100.00")),
        total_tva=Champ.lu(D("20.00")),
        total_port=Champ.lu(D("30.00")),
        timbre_fiscal=Champ.lu(D("0.25")),
        total_ttc=Champ.lu(D("150.25")),
    )
    assert valider(f) == []


def test_rv08_taux_hors_bareme():
    f = Facture(bandes_tva=[BandeTVA(taux=Champ.lu(D("19")))])  # 19% n'existe pas
    anomalies = valider(f)

    assert len(anomalies) == 1
    assert anomalies[0].regle == "RV-08"
    assert anomalies[0].severite is Severite.ERREUR


# ---------------------------------------------------------------------------
# Validation : les formats / la forme avertissent
# ---------------------------------------------------------------------------


def test_rv11_dates_incoherentes_avertissement_non_bloquant():
    f = Facture(
        date_emission=Champ.lu(date(2026, 9, 30)),
        date_echeance=Champ.lu(date(2026, 9, 1)),  # anterieure a l'emission
    )
    anomalies = valider(f)

    assert len(anomalies) == 1
    assert anomalies[0].severite is Severite.AVERTISSEMENT
    assert not a_des_erreurs(anomalies)  # n'interdit PAS l'auto-acceptation


# ---------------------------------------------------------------------------
# Aller-retour JSON : le schema est bien la source de verite unique
# ---------------------------------------------------------------------------


def test_facture_depuis_json_brut():
    """Le JSON que produira le modele (decodage contraint, EF-12) se charge
    tel quel dans le schema — y compris le mot-cle 'if' du fournisseur."""
    brut = {
        "numero_facture": {"valeur": "F-2026-0815", "source": "lu"},
        "total_ttc": {"valeur": "1234.56", "valeur_brute": "1 234,56 DH", "source": "lu"},
        "fournisseur": {"nom": {"valeur": "STE ATLAS SARL"}, "if": {"valeur": "12345678"}},
        "bandes_tva": [{"taux": {"valeur": "20"}}],
        "extra": {"mention_pied_de_page": "Merci de votre confiance"},
    }
    f = Facture.model_validate(brut)

    assert f.total_ttc is not None and f.total_ttc.valeur == D("1234.56")
    assert f.total_ttc.valeur_brute == "1 234,56 DH"
    assert f.fournisseur is not None and f.fournisseur.if_ is not None
    assert f.fournisseur.if_.valeur == "12345678"
    # Rien n'est perdu : ce qui n'entre pas dans le schema va dans extra (EF-15)
    assert f.extra["mention_pied_de_page"] == "Merci de votre confiance"

    # Et le schema JSON pour le decodage contraint sort d'ici, nulle part ailleurs :
    assert "properties" in Facture.model_json_schema()


# ---------------------------------------------------------------------------
# Ma premiere regle : RD-02
# ---------------------------------------------------------------------------


def test_rd02_ht_et_taux_derivent_tva_puis_ttc():
    f = Facture(
        total_ht=Champ.lu(D("100.00")),
        bandes_tva=[BandeTVA(taux=Champ.lu(D("20")))],
    )
    appliquees = appliquer_derivations(f)

    assert "rd_02" in appliquees
    assert f.total_tva is not None and f.total_tva.valeur == D("20.00")
    assert f.total_tva.regle == "RD-02"
    # Le TTC arrive par chainage : RD-02 produit la TVA, RD-05 finit le travail
    assert f.total_ttc is not None and f.total_ttc.valeur == D("120.00")
    assert f.total_ttc.regle == "RD-05"
    assert valider(f) == []
    

# ---------------------------------------------------------------------------
# RD-06 : le net a payer
# ---------------------------------------------------------------------------


def test_rd06_ttc_et_acompte_derivent_net_a_payer():
    # Facture inventee : TTC = 120, le client a deja verse 50 d'acompte
    f = Facture(
        total_ttc=Champ.lu(D("120")),
        acompte=Champ.lu(D("50")),
    )
    appliquees = appliquer_derivations(f)

    assert "rd_06" in appliquees
    # Combien reste-t-il a payer ? C'est TOI qui ecris le montant attendu :
    assert f.net_a_payer is not None and f.net_a_payer.valeur == D("70")
    assert f.net_a_payer.source is Source.DERIVE
    assert f.net_a_payer.regle == "RD-06"