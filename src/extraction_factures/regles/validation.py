"""Regles de validation (CDC section 5.6, RV-01 a RV-12).

Deux principes graves dans le marbre :

1. Chaque regle est CONDITIONNELLE : elle ne s'execute que si tous les
   champs qu'elle met en jeu sont presents. L'absence d'un champ n'est
   jamais une erreur ; une incoherence entre deux champs presents en est une.

2. Les mathematiques bloquent, les formats avertissent (encadre 5.6 du CDC).
   - ERREUR : incoherence arithmetique demontrable -> interdit l'auto-acceptation.
   - AVERTISSEMENT : anomalie de forme ou controle non tranchable -> signale,
     non bloquant. Classer un controle de format en erreur noierait la file
     de relecture sous les fausses alertes.

Implementees en exemple : RV-06 (erreur), RV-08 (erreur), RV-11 (avertissement).
A ecrire toi-meme : RV-01 a RV-05, RV-07, RV-09, RV-10, RV-12
(enonces exacts dans le tableau 5.6 du CDC). Test d'abord, toujours.
"""

from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

from regles.commun import BAREME_TVA, arrondi, egaux, present
from schema.modeles import Facture


class Severite(str, Enum):
    ERREUR = "erreur"
    AVERTISSEMENT = "avertissement"


class Anomalie(BaseModel):
    """Une regle qui n'a pas passe. C'est ce que verra l'ecran de relecture
    (EF-24), donc le message doit etre comprehensible par un comptable,
    pas par un developpeur."""

    regle: str
    severite: Severite
    message: str
    champs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Regles implementees (exemples a imiter)
# ---------------------------------------------------------------------------


def rv_06(f: Facture) -> list[Anomalie]:
    """total HT + total TVA (+ port + timbre - remise) = total TTC. ERREUR.

    Miroir exact de la formule RD-05 : si les trois totaux ont ete LUS,
    on verifie leur coherence au lieu de deriver.
    NB : l'imputation exacte du port (HT ? TVA propre ?) est une regle de
    gestion a trancher avec le comptable de l'entreprise (moyen prevu
    section 13 du CDC) — la formule ci-dessous suit le CDC a la lettre.
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
        (f.total_remise, -1),
    ):
        if champ is not None and present(champ):
            assert champ.valeur is not None
            attendu += signe * champ.valeur
            nb_operandes += 1

    attendu = arrondi(attendu)
    if egaux(attendu, f.total_ttc.valeur, nb_operandes=nb_operandes):
        return []

    return [
        Anomalie(
            regle="RV-06",
            severite=Severite.ERREUR,
            message=(
                f"Le total TTC lu ({f.total_ttc.valeur}) ne correspond pas a "
                f"HT + TVA et termes annexes ({attendu})."
            ),
            champs=["total_ht", "total_tva", "total_ttc"],
        )
    ]


def rv_08(f: Facture) -> list[Anomalie]:
    """Tout taux de TVA present appartient au bareme legal. ERREUR."""
    anomalies: list[Anomalie] = []

    for i, bande in enumerate(f.bandes_tva):
        if bande.taux is not None and present(bande.taux):
            assert bande.taux.valeur is not None
            if bande.taux.valeur not in BAREME_TVA:
                anomalies.append(
                    Anomalie(
                        regle="RV-08",
                        severite=Severite.ERREUR,
                        message=(
                            f"Taux de TVA {bande.taux.valeur}% hors bareme legal "
                            f"(bande {i + 1})."
                        ),
                        champs=[f"bandes_tva[{i}].taux"],
                    )
                )

    for i, ligne in enumerate(f.lignes):
        if ligne.taux_tva is not None and present(ligne.taux_tva):
            assert ligne.taux_tva.valeur is not None
            if ligne.taux_tva.valeur not in BAREME_TVA:
                anomalies.append(
                    Anomalie(
                        regle="RV-08",
                        severite=Severite.ERREUR,
                        message=(
                            f"Taux de TVA {ligne.taux_tva.valeur}% hors bareme "
                            f"legal (ligne {i + 1})."
                        ),
                        champs=[f"lignes[{i}].taux_tva"],
                    )
                )

    return anomalies


def rv_11(f: Facture) -> list[Anomalie]:
    """Date d'emission <= date d'echeance. AVERTISSEMENT.

    Avertissement et non erreur : une date incoherente peut venir d'une
    coquille du fournisseur lui-meme — on ne peut pas trancher avec
    certitude, donc on signale sans bloquer.
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
        Anomalie(
            regle="RV-11",
            severite=Severite.AVERTISSEMENT,
            message=(
                f"La date d'emission ({f.date_emission.valeur}) est posterieure "
                f"a la date d'echeance ({f.date_echeance.valeur})."
            ),
            champs=["date_emission", "date_echeance"],
        )
    ]


# ---------------------------------------------------------------------------
# TODO stagiaire — a implementer semaine 2, test d'abord
# ---------------------------------------------------------------------------
#
# rv_01 : qte x PU - remise = montant HT ligne                       ERREUR
# rv_02 : somme des HT lignes = total HT (remise globale, port)      ERREUR
# rv_03 : document valorise TTC seul : somme lignes = total TTC      ERREUR
# rv_04 : par bande : base x taux = montant TVA de la bande          ERREUR
# rv_05 : somme des bandes = total TVA                               ERREUR
# rv_07 : TTC - acompte - escompte = net a payer                     ERREUR
# rv_09 : ICE = 15 chiffres                                          ERREUR
# rv_10 : Luhn du SIRET, format TVA intracommunautaire        AVERTISSEMENT
# rv_12 : devise unique sur tout le document                  AVERTISSEMENT


REGLES_VALIDATION: list[Callable[[Facture], list[Anomalie]]] = [
    rv_06,
    rv_08,
    rv_11,
    # rv_01 ... rv_12 : a ajouter au fur et a mesure
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
