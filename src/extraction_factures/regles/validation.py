"""Regles de validation (CDC section 5.6, RV-01 a RV-12).

Deux principes graves dans le marbre :

1. Chaque regle est CONDITIONNELLE : elle ne s'execute que si tous les
   champs qu'elle met en jeu sont presents. L'absence d'un champ n'est
   jamais une erreur ; une incoherence entre deux champs presents en est une.

2. Les mathematiques bloquent, les formats avertissent (encadre 5.6 du CDC).
   - ERREUR : incoherence arithmetique demontrable -> interdit l'auto-acceptation.
   - AVERTISSEMENT : anomalie de forme ou controle non tranchable -> signale,
     non bloquant.
"""

import re
from decimal import Decimal
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

from regles.commun import (
    BAREME_TVA,
    DEVISES_CONNUES,
    arrondi,
    egaux,
    luhn_valide,
    present,
)
from schema.modeles import Facture


class Severite(str, Enum):
    ERREUR = "erreur"
    AVERTISSEMENT = "avertissement"


class Anomalie(BaseModel):
    """Une regle qui n'a pas passe. C'est ce que verra l'ecran de relecture
    (EF-24), donc le message doit etre comprehensible par un comptable."""

    regle: str
    severite: Severite
    message: str
    champs: list[str] = Field(default_factory=list)


def _erreur(regle: str, message: str, champs: list[str]) -> Anomalie:
    return Anomalie(regle=regle, severite=Severite.ERREUR, message=message, champs=champs)


def _avertissement(regle: str, message: str, champs: list[str]) -> Anomalie:
    return Anomalie(
        regle=regle, severite=Severite.AVERTISSEMENT, message=message, champs=champs
    )


# ---------------------------------------------------------------------------
# Les mathematiques bloquent (ERREUR)
# ---------------------------------------------------------------------------


def rv_01(f: Facture) -> list[Anomalie]:
    """Par ligne : qte x PU - remise = montant HT de la ligne."""
    anomalies: list[Anomalie] = []
    for i, l in enumerate(f.lignes):
        if not present(l.quantite, l.prix_unitaire_ht, l.montant_ht):
            continue
        assert l.quantite is not None and l.quantite.valeur is not None
        assert l.prix_unitaire_ht is not None and l.prix_unitaire_ht.valeur is not None
        assert l.montant_ht is not None and l.montant_ht.valeur is not None
        attendu = l.quantite.valeur * l.prix_unitaire_ht.valeur
        nb_operandes = 2
        if l.montant_remise is not None and present(l.montant_remise):
            assert l.montant_remise.valeur is not None
            attendu -= l.montant_remise.valeur
            nb_operandes += 1
        if not egaux(arrondi(attendu), l.montant_ht.valeur, nb_operandes=nb_operandes):
            anomalies.append(
                _erreur(
                    "RV-01",
                    f"Ligne {i + 1} : qte x PU - remise = {arrondi(attendu)}, "
                    f"mais le montant HT lu est {l.montant_ht.valeur}.",
                    [f"lignes[{i}].montant_ht"],
                )
            )
    return anomalies


def rv_02(f: Facture) -> list[Anomalie]:
    """Somme des montants HT des lignes = total HT (remise globale deduite).

    NB : le port rejoint le calcul au niveau TTC (coherent avec RD-04/RD-05) ;
    son imputation exacte est une regle de gestion a confirmer avec le
    comptable (moyen prevu section 13 du CDC).
    """
    if not f.lignes or not present(f.total_ht):
        return []
    montants = [
        l.montant_ht.valeur
        for l in f.lignes
        if l.montant_ht is not None and present(l.montant_ht)
    ]
    if len(montants) != len(f.lignes):
        return []  # des lignes sans montant : la comparaison n'a pas de sens

    assert f.total_ht is not None and f.total_ht.valeur is not None
    attendu = sum(montants, start=Decimal("0"))
    nb_operandes = len(montants)
    if f.total_remise is not None and present(f.total_remise):
        assert f.total_remise.valeur is not None
        attendu -= f.total_remise.valeur
        nb_operandes += 1
    if egaux(arrondi(attendu), f.total_ht.valeur, nb_operandes=nb_operandes):
        return []
    return [
        _erreur(
            "RV-02",
            f"La somme des lignes ({arrondi(attendu)}) ne correspond pas "
            f"au total HT lu ({f.total_ht.valeur}).",
            ["total_ht"],
        )
    ]


def rv_03(f: Facture) -> list[Anomalie]:
    """Document valorise en TTC seulement : somme des lignes = total TTC.

    Ne se declenche que si le total HT est ABSENT (sinon c'est RV-02 qui
    fait foi) — cas "BL valorise en TTC" de la section 4.1 du CDC.
    """
    if present(f.total_ht) or not present(f.total_ttc) or not f.lignes:
        return []
    montants = [
        l.montant_ttc.valeur
        for l in f.lignes
        if l.montant_ttc is not None and present(l.montant_ttc)
    ]
    if len(montants) != len(f.lignes):
        return []

    assert f.total_ttc is not None and f.total_ttc.valeur is not None
    attendu = arrondi(sum(montants, start=Decimal("0")))
    if egaux(attendu, f.total_ttc.valeur, nb_operandes=len(montants)):
        return []
    return [
        _erreur(
            "RV-03",
            f"La somme TTC des lignes ({attendu}) ne correspond pas "
            f"au total TTC lu ({f.total_ttc.valeur}).",
            ["total_ttc"],
        )
    ]


def rv_04(f: Facture) -> list[Anomalie]:
    """Par bande de TVA : base x taux = montant de TVA de la bande."""
    anomalies: list[Anomalie] = []
    for i, b in enumerate(f.bandes_tva):
        if not present(b.taux, b.base_ht, b.montant_tva):
            continue
        assert b.taux is not None and b.taux.valeur is not None
        assert b.base_ht is not None and b.base_ht.valeur is not None
        assert b.montant_tva is not None and b.montant_tva.valeur is not None
        attendu = arrondi(b.base_ht.valeur * b.taux.valeur / Decimal("100"))
        if not egaux(attendu, b.montant_tva.valeur, nb_operandes=2):
            anomalies.append(
                _erreur(
                    "RV-04",
                    f"Bande {i + 1} ({b.taux.valeur}%) : base x taux = {attendu}, "
                    f"mais le montant de TVA lu est {b.montant_tva.valeur}.",
                    [f"bandes_tva[{i}].montant_tva"],
                )
            )
    return anomalies


def rv_05(f: Facture) -> list[Anomalie]:
    """Somme des bandes de TVA = total TVA."""
    if not f.bandes_tva or not present(f.total_tva):
        return []
    montants = [
        b.montant_tva.valeur
        for b in f.bandes_tva
        if b.montant_tva is not None and present(b.montant_tva)
    ]
    if len(montants) != len(f.bandes_tva):
        return []

    assert f.total_tva is not None and f.total_tva.valeur is not None
    attendu = arrondi(sum(montants, start=Decimal("0")))
    if egaux(attendu, f.total_tva.valeur, nb_operandes=len(montants)):
        return []
    return [
        _erreur(
            "RV-05",
            f"La somme des bandes de TVA ({attendu}) ne correspond pas "
            f"au total TVA lu ({f.total_tva.valeur}).",
            ["total_tva"],
        )
    ]


def rv_06(f: Facture) -> list[Anomalie]:
    """total HT + total TVA (+ port + timbre) = total TTC.

    Convention remise (a confirmer avec le comptable) : la remise globale
    est deja imputee dans le total HT (RV-02) ; on ne la re-deduit pas ici.
    """
    if not present(f.total_ht, f.total_tva, f.total_ttc):
        return []

    assert f.total_ht is not None and f.total_ht.valeur is not None
    assert f.total_tva is not None and f.total_tva.valeur is not None
    assert f.total_ttc is not None and f.total_ttc.valeur is not None

    attendu = f.total_ht.valeur + f.total_tva.valeur
    nb_operandes = 2
    for champ, signe in (
        (f.total_port, 1),
        (f.timbre_fiscal, 1),
    ):
        if champ is not None and present(champ):
            assert champ.valeur is not None
            attendu += signe * champ.valeur
            nb_operandes += 1

    attendu = arrondi(attendu)
    if egaux(attendu, f.total_ttc.valeur, nb_operandes=nb_operandes):
        return []
    return [
        _erreur(
            "RV-06",
            f"Le total TTC lu ({f.total_ttc.valeur}) ne correspond pas a "
            f"HT + TVA et termes annexes ({attendu}).",
            ["total_ht", "total_tva", "total_ttc"],
        )
    ]


def rv_07(f: Facture) -> list[Anomalie]:
    """TTC - acompte - escompte = net a payer.

    Acompte et escompte sont des termes optionnels : sans eux, le net a
    payer doit simplement egaler le TTC. Un ecart inexplique entre net et
    TTC est suspect (acompte rate a l'extraction ?) -> erreur, relecture.
    """
    if not present(f.total_ttc, f.net_a_payer):
        return []

    assert f.total_ttc is not None and f.total_ttc.valeur is not None
    assert f.net_a_payer is not None and f.net_a_payer.valeur is not None
    attendu = f.total_ttc.valeur
    nb_operandes = 1
    for champ in (f.acompte, f.escompte):
        if champ is not None and present(champ):
            assert champ.valeur is not None
            attendu -= champ.valeur
            nb_operandes += 1
    attendu = arrondi(attendu)
    if egaux(attendu, f.net_a_payer.valeur, nb_operandes=nb_operandes):
        return []
    return [
        _erreur(
            "RV-07",
            f"TTC - acompte - escompte = {attendu}, mais le net a payer "
            f"lu est {f.net_a_payer.valeur}.",
            ["net_a_payer"],
        )
    ]


def rv_08(f: Facture) -> list[Anomalie]:
    """Tout taux de TVA present appartient au bareme legal."""
    anomalies: list[Anomalie] = []
    for i, bande in enumerate(f.bandes_tva):
        if bande.taux is not None and present(bande.taux):
            assert bande.taux.valeur is not None
            if bande.taux.valeur not in BAREME_TVA:
                anomalies.append(
                    _erreur(
                        "RV-08",
                        f"Taux de TVA {bande.taux.valeur}% hors bareme legal "
                        f"(bande {i + 1}).",
                        [f"bandes_tva[{i}].taux"],
                    )
                )
    for i, ligne in enumerate(f.lignes):
        if ligne.taux_tva is not None and present(ligne.taux_tva):
            assert ligne.taux_tva.valeur is not None
            if ligne.taux_tva.valeur not in BAREME_TVA:
                anomalies.append(
                    _erreur(
                        "RV-08",
                        f"Taux de TVA {ligne.taux_tva.valeur}% hors bareme "
                        f"legal (ligne {i + 1}).",
                        [f"lignes[{i}].taux_tva"],
                    )
                )
    return anomalies


def rv_09(f: Facture) -> list[Anomalie]:
    """Identifiants fiscaux : l'ICE comporte exactement 15 chiffres."""
    anomalies: list[Anomalie] = []
    candidats = []
    if f.fournisseur is not None:
        candidats.append(("fournisseur.ice", f.fournisseur.ice))
    if f.client is not None:
        candidats.append(("client.ice", f.client.ice))
    for chemin, champ in candidats:
        if champ is None or not present(champ):
            continue
        assert champ.valeur is not None
        ice = champ.valeur.replace(" ", "")
        if not (len(ice) == 15 and ice.isdigit()):
            anomalies.append(
                _erreur(
                    "RV-09",
                    f"ICE invalide ({champ.valeur}) : 15 chiffres attendus.",
                    [chemin],
                )
            )
    return anomalies


# ---------------------------------------------------------------------------
# Les formats avertissent (AVERTISSEMENT)
# ---------------------------------------------------------------------------

FORMAT_TVA_INTRA = re.compile(r"^[A-Z]{2}[0-9A-Za-z]{2,13}$")


def rv_10(f: Facture) -> list[Anomalie]:
    """Cles de controle et formats : Luhn du SIRET, format TVA intracommunautaire.

    AVERTISSEMENT et non erreur (encadre 5.6 du CDC) : une cle qu'on ne
    peut pas verifier de facon autoritaire ne doit pas bloquer, sous peine
    de noyer la file de relecture.
    """
    anomalies: list[Anomalie] = []
    if f.fournisseur is None:
        return anomalies

    siret = f.fournisseur.siret
    if siret is not None and present(siret):
        assert siret.valeur is not None
        brut = siret.valeur.replace(" ", "")
        if not (len(brut) == 14 and luhn_valide(brut)):
            anomalies.append(
                _avertissement(
                    "RV-10",
                    f"SIRET suspect ({siret.valeur}) : 14 chiffres et cle de "
                    f"Luhn attendus.",
                    ["fournisseur.siret"],
                )
            )

    tva_intra = f.fournisseur.tva_intra
    if tva_intra is not None and present(tva_intra):
        assert tva_intra.valeur is not None
        brut = tva_intra.valeur.replace(" ", "")
        if not FORMAT_TVA_INTRA.match(brut):
            anomalies.append(
                _avertissement(
                    "RV-10",
                    f"Numero de TVA intracommunautaire au format inattendu "
                    f"({tva_intra.valeur}).",
                    ["fournisseur.tva_intra"],
                )
            )
    return anomalies


def rv_11(f: Facture) -> list[Anomalie]:
    """Date d'emission <= date d'echeance. AVERTISSEMENT.

    (La partie "date plausible / bornes configurables" du RV-11 est un
    TODO : elle demandera un parametre de configuration.)
    """
    if not present(f.date_emission, f.date_echeance):
        return []

    assert f.date_emission is not None and f.date_emission.valeur is not None
    assert f.date_echeance is not None and f.date_echeance.valeur is not None

    if f.date_emission.valeur <= f.date_echeance.valeur:
        return []
    return [
        _avertissement(
            "RV-11",
            f"La date d'emission ({f.date_emission.valeur}) est posterieure "
            f"a la date d'echeance ({f.date_echeance.valeur}).",
            ["date_emission", "date_echeance"],
        )
    ]


def rv_12(f: Facture) -> list[Anomalie]:
    """Devise declaree coherente : code ISO 4217 connu.

    La verification "devise unique sur tout le document" complete exigera
    l'information de la couche d'extraction (symboles releves champ par
    champ dans valeur_brute) : a enrichir en semaine 3 avec la
    normalisation EF-18/EF-19.
    """
    if not present(f.devise):
        return []
    assert f.devise is not None and f.devise.valeur is not None
    if f.devise.valeur in DEVISES_CONNUES:
        return []
    return [
        _avertissement(
            "RV-12",
            f"Devise inattendue ({f.devise.valeur}) : code ISO 4217 attendu "
            f"(ex. MAD, EUR).",
            ["devise"],
        )
    ]


REGLES_VALIDATION: list[Callable[[Facture], list[Anomalie]]] = [
    rv_01,
    rv_02,
    rv_03,
    rv_04,
    rv_05,
    rv_06,
    rv_07,
    rv_08,
    rv_09,
    rv_10,
    rv_11,
    rv_12,
]


def valider(f: Facture) -> list[Anomalie]:
    """Execute toutes les regles de validation et rassemble les anomalies."""
    anomalies: list[Anomalie] = []
    for regle in REGLES_VALIDATION:
        anomalies.extend(regle(f))
    return anomalies


def a_des_erreurs(anomalies: list[Anomalie]) -> bool:
    """Vrai si au moins une anomalie de severite ERREUR est presente.

    C'est la moitie de la porte d'auto-acceptation (EF-22) ; l'autre
    moitie — la concordance des lectures independantes — arrivera en
    semaine 5 avec la double lecture.
    """
    return any(a.severite is Severite.ERREUR for a in anomalies)
