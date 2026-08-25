"""Tests de la normalisation (EF-17 / EF-18)."""

from datetime import date
from decimal import Decimal

from extraction.normalisation import (
    date_depuis_texte,
    montant_depuis_texte,
    taux_depuis_texte,
)

D = Decimal


def test_montants_formats_courants():
    assert montant_depuis_texte("1\u00a0234,56") == D("1234.56")   # espace insecable
    assert montant_depuis_texte("1 234,56 DH") == D("1234.56")
    assert montant_depuis_texte("1.234,56") == D("1234.56")        # style allemand
    assert montant_depuis_texte("1,234.56") == D("1234.56")        # style anglais
    assert montant_depuis_texte("120") == D("120")
    assert montant_depuis_texte("6 347,00 MAD") == D("6347.00")


def test_montants_illisibles_rendent_none():
    assert montant_depuis_texte("abc") is None
    assert montant_depuis_texte("") is None
    assert montant_depuis_texte(None) is None


def test_dates_formats_courants():
    assert date_depuis_texte("08/04/2026") == date(2026, 4, 8)
    assert date_depuis_texte("08-04-2026") == date(2026, 4, 8)
    assert date_depuis_texte("08.04.2026") == date(2026, 4, 8)
    assert date_depuis_texte("2026-04-08") == date(2026, 4, 8)
    assert date_depuis_texte("12 mars 2026") == date(2026, 3, 12)
    assert date_depuis_texte("Date d'emission : 08/04/2026") == date(2026, 4, 8)


def test_dates_impossibles_rendent_none():
    assert date_depuis_texte("31/02/2026") is None
    assert date_depuis_texte("bonjour") is None


def test_taux():
    assert taux_depuis_texte("20%") == D("20")
    assert taux_depuis_texte("TVA 7 % incluse") == D("7")
    assert taux_depuis_texte("aucun") is None
