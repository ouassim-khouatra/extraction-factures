"""Normalisation des valeurs lues (CDC EF-17, EF-18, EF-19).

Transforme les chaines telles qu'imprimees sur les documents en valeurs
canoniques : "6 347,00 DH" -> Decimal("6347.00"), "12 mars 2026" -> date.
Chaque fonction rend None si elle ne sait pas trancher : l'echec de
normalisation n'est jamais un plantage, c'est un champ qui reste brut.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

# Symboles monetaires a retirer (EF-18)
_MONNAIES = re.compile(r"(MAD|DHS?|DH|EUR|€)\s*", re.IGNORECASE)
# Tous les types d'espaces (normale, insecable, fine insecable)
_ESPACES = re.compile(r"[\s\u00a0\u202f]+")

MOIS_FR = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8, "août": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "décembre": 12,
}


def montant_depuis_texte(brut: Optional[str]) -> Optional[Decimal]:
    """'1 234,56 DH' / '1.234,56' / '1,234.56' -> Decimal('1234.56').

    Regle de decision pour le separateur decimal : le DERNIER separateur
    ('.' ou ',') suivi de 1 ou 2 chiffres en fin de nombre est decimal ;
    tous les autres sont des separateurs de milliers.
    (Le CDC demande, a terme, d'arbitrer aussi par la coherence
    arithmetique du document : ce sera le role du filet de validation.)
    """
    if not brut:
        return None
    texte = _MONNAIES.sub("", brut)
    texte = _ESPACES.sub("", texte).strip()
    negatif = texte.startswith("-") or (texte.startswith("(") and texte.endswith(")"))
    texte = texte.strip("()-+")
    if not texte or not re.fullmatch(r"[0-9.,]+", texte):
        return None

    derniere_virgule = texte.rfind(",")
    dernier_point = texte.rfind(".")
    position = max(derniere_virgule, dernier_point)
    if position >= 0 and 1 <= len(texte) - position - 1 <= 2:
        entier = re.sub(r"[.,]", "", texte[:position])
        decimales = texte[position + 1:]
        texte = f"{entier}.{decimales}"
    else:
        texte = re.sub(r"[.,]", "", texte)
    try:
        valeur = Decimal(texte)
    except InvalidOperation:
        return None
    return -valeur if negatif else valeur


def date_depuis_texte(brut: Optional[str]) -> Optional[date]:
    """Reconnait jj/mm/aaaa, jj-mm-aaaa, jj.mm.aaaa, aaaa-mm-jj
    et '12 mars 2026' -> date ISO (EF-17)."""
    if not brut:
        return None
    texte = brut.strip().lower()

    m = re.search(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b", texte)
    if m:
        jour, mois, annee = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(annee, mois, jour)
        except ValueError:
            return None
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", texte)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})(?:er)?\s+([a-zéû]+)\s+(\d{4})\b", texte)
    if m and m.group(2) in MOIS_FR:
        try:
            return date(int(m.group(3)), MOIS_FR[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def taux_depuis_texte(brut: Optional[str]) -> Optional[Decimal]:
    """'20%' / '20 %' / 'TVA 20%' -> Decimal('20')."""
    if not brut:
        return None
    m = re.search(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", brut)
    if not m:
        return None
    return Decimal(m.group(1).replace(",", "."))
