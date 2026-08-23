"""Conventions numeriques communes a toutes les regles.

Le CDC (section 5.6) exige que la tolerance d'arrondi et la convention
d'arrondi soient ecrites EN UN SEUL ENDROIT du code, et testees.
C'est ici, et nulle part ailleurs. Si une regle arrondit ou compare des
montants sans passer par ce module, c'est un bug de conception.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from schema.modeles import Champ

# Arrondi commercial a deux decimales (CDC section 5.6).
DEUX_DECIMALES = Decimal("0.01")

# Tolerance : +/- 0,01 unite monetaire PAR OPERANDE engage dans le calcul.
# Une somme de 12 lignes tolere donc +/- 0,12.
TOLERANCE_PAR_OPERANDE = Decimal("0.01")

# Bareme legal des taux de TVA (RV-08 / RD-08). En pourcents.
BAREME_TVA = (
    Decimal("0"),
    Decimal("7"),
    Decimal("10"),
    Decimal("14"),
    Decimal("20"),
)

# Ecart maximal pour aligner un taux calcule sur le bareme (RD-08), en points.
ECART_ALIGNEMENT_TAUX = Decimal("0.5")

# Codes devise acceptes sans avertissement (RV-12, EF-19).
# La normalisation "DH"/"Dhs" -> "MAD" arrivera en semaine 3 (EF-18).
DEVISES_CONNUES = {"MAD", "EUR", "USD", "GBP", "CHF", "JPY"}


def arrondi(montant: Decimal) -> Decimal:
    """Arrondi commercial a deux decimales — LE seul arrondi du projet."""
    return montant.quantize(DEUX_DECIMALES, rounding=ROUND_HALF_UP)


def egaux(a: Decimal, b: Decimal, nb_operandes: int = 1) -> bool:
    """Egalite de deux montants a la tolerance du CDC pres.

    `nb_operandes` = nombre de valeurs engagees dans le calcul qui a
    produit `a` (ou `b`). Chaque operande apporte +/- 0,01 de tolerance.
    """
    return abs(a - b) <= TOLERANCE_PAR_OPERANDE * nb_operandes


def present(*champs: Optional[Champ[Any]]) -> bool:
    """Vrai si TOUS les champs donnes existent ET portent une valeur.

    C'est la brique des regles conditionnelles (CDC section 4.c) :
    une regle ne se declenche que si `present(...)` est vrai pour tous
    les champs qu'elle met en jeu. L'absence n'est JAMAIS une erreur.
    """
    return all(c is not None and c.valeur is not None for c in champs)


def luhn_valide(numero: str) -> bool:
    """Cle de Luhn (utilisee par RV-10 pour le SIRET).

    Principe : en partant de la droite, on double un chiffre sur deux
    (en retranchant 9 si le double depasse 9) ; la somme totale doit
    etre un multiple de 10.
    """
    if not numero.isdigit():
        return False
    total = 0
    for i, caractere in enumerate(reversed(numero)):
        chiffre = int(caractere)
        if i % 2 == 1:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        total += chiffre
    return total % 10 == 0
